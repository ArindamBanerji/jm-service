"""Label Studio task adapter backed by the labeling repository."""
from __future__ import annotations

import json
import hashlib
import os
from datetime import datetime, timezone
from hmac import compare_digest
from pathlib import Path
from threading import Lock
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import repository
from auth import Tenant, scoped_domain_id
from db.connection import get_db
from db.models import LabelLog
from jm_core import DomainConfig, JudgmentMemoryEngine
from labeling_router import IngestItem, _category_stats, _ingest
from policy_engine import AutonomyTier, evaluate_domain

router = APIRouter(prefix="/v1/label-studio", tags=["Label Studio"])
Session = Annotated[AsyncSession, Depends(get_db)]
_config_lock = Lock()
_default_map = {"model_confidence": "data.ml_confidence",
                "annotator_agreement": "data.agreement_score"}


def _authorize(token: Annotated[str | None, Header(alias="X-LS-Token")] = None) -> None:
    expected = os.getenv("LABEL_STUDIO_TOKEN")
    if not expected:
        raise HTTPException(503, detail="Label Studio token is not configured")
    if token is None or not compare_digest(token, expected):
        raise HTTPException(401, detail="Invalid Label Studio token")


Authorized = Annotated[None, Depends(_authorize)]


class ConnectorConfig(BaseModel):
    tenant_id: str | None = None
    domain_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    factor_map: dict[str, str] = Field(min_length=2)
    category_field: str = "data.category"
    ground_truth_field: str | None = "data.ground_truth"


def _config_path() -> Path:
    return Path(os.getenv("LS_CONFIG_PATH", "/data/ls_config.json"))


def _validate_config(config: ConnectorConfig) -> ConnectorConfig:
    if any(not name.strip() or not field.startswith("data.") or len(field) <= 5
           for name, field in config.factor_map.items()):
        raise HTTPException(422, detail="Factor names must be nonempty and mapped from data fields")
    if not config.category_field.startswith("data."):
        raise HTTPException(422, detail="category_field must start with data.")
    if config.ground_truth_field is not None and not config.ground_truth_field.startswith("data."):
        raise HTTPException(422, detail="ground_truth_field must start with data.")
    return config


def _saved_configs() -> dict[str, dict[str, Any]]:
    path = _config_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _project_id(project: Any) -> str:
    value = project.get("id") if isinstance(project, dict) else project
    if value is None or not str(value).strip():
        raise HTTPException(422, detail="Label Studio project ID is required")
    return str(value)


def _config(project: Any, tenant: str | None = None) -> ConnectorConfig:
    project_id = _project_id(project)
    saved = _saved_configs().get(f"{tenant}\0{project_id}" if tenant is not None else project_id)
    if saved:
        return ConnectorConfig.model_validate(saved)
    mapping = json.loads(os.getenv("LS_FACTOR_MAP", json.dumps(_default_map)))
    return _validate_config(ConnectorConfig(
        domain_id=os.getenv("LABEL_STUDIO_DOMAIN_ID", f"ls-{project_id}"),
        project_id=project_id, factor_map=mapping,
    ))


def _bind_config(config: ConnectorConfig, tenant: str) -> ConnectorConfig:
    if config.tenant_id is not None and config.tenant_id != tenant:
        raise HTTPException(404, detail="Project not found")
    return config.model_copy(update={"domain_id": scoped_domain_id(tenant, config.domain_id),
                                      "tenant_id": tenant})


def _field(data: dict[str, Any], path: str) -> Any:
    value: Any = {"data": data}
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _task_values(task: dict[str, Any], config: ConnectorConfig) -> tuple[str, str, dict[str, float]]:
    if task.get("id") is None or not isinstance(task.get("data"), dict):
        raise HTTPException(422, detail="Task requires id and data")
    data = task["data"]
    factors: dict[str, float] = {}
    for name, path in config.factor_map.items():
        value = _field(data, path)
        if value is None:
            value = 0.5
        if isinstance(value, bool):
            raise HTTPException(422, detail=f"Invalid factor {name}")
        try:
            factors[name] = float(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, detail=f"Invalid factor {name}") from exc
    category = _field(data, config.category_field) or "default"
    return str(task["id"]), str(category), factors


async def _ensure_domain(session: AsyncSession, config: ConnectorConfig) -> None:
    domain = await repository.get_domain(session, config.domain_id)
    if domain is None:
        await repository.create_domain(session, config.domain_id, config.domain_id,
                                       DomainConfig(config.domain_id, config.domain_id,
                                                    list(config.factor_map), ["default"],
                                                    ["approve", "reject"]))
    elif set(domain.config_json["factors"]) != set(config.factor_map):
        raise HTTPException(409, detail="Configured factors differ from the existing domain")


def _action(annotation: dict[str, Any]) -> str:
    if isinstance(annotation.get("actual_action"), str):
        return annotation["actual_action"]
    for result in annotation.get("result", []):
        value = result.get("value", {})
        for key in ("choices", "labels", "rectanglelabels"):
            if isinstance(value.get(key), list) and value[key]:
                return str(value[key][0])
    raise HTTPException(422, detail="Annotation action is unavailable")


@router.post("/configure")
async def configure(config: ConnectorConfig, _: Authorized, tenant: Tenant) -> ConnectorConfig:
    _validate_config(config)
    config = config.model_copy(update={"tenant_id": tenant})
    path = _config_path()
    with _config_lock:
        saved = _saved_configs()
        saved[f"{tenant}\0{config.project_id}"] = config.model_dump()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(saved), encoding="utf-8")
        temporary.replace(path)
    return config


@router.post("/setup")
async def setup(payload: dict[str, Any], session: Session, _: Authorized) -> dict[str, str]:
    config = _config(payload.get("project"))
    setup_tenant = config.tenant_id or os.getenv("LABEL_STUDIO_TENANT_ID")
    if setup_tenant:
        session.info["tenant_id"] = setup_tenant
        await _ensure_domain(session, _bind_config(config, setup_tenant))
    return {"model_version": "jm-v1"}


@router.post("/predict")
async def predict(payload: dict[str, Any], session: Session, _: Authorized, tenant: Tenant) -> dict[str, list[dict[str, Any]]]:
    config = _bind_config(_config(payload.get("project"), tenant), tenant)
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise HTTPException(422, detail="tasks must be a list")
    await _ensure_domain(session, config)
    predictions = []
    for task in tasks:
        label_id, category, factors = _task_values(task, config)
        annotator_id = str(task.get("annotator_id")) if task.get("annotator_id") is not None else None
        existing = await session.scalar(select(LabelLog).where(
            LabelLog.domain_id == config.domain_id, LabelLog.tenant_id == tenant,
            LabelLog.label_id == label_id))
        if existing is not None:
            if existing.category != category or existing.factors_json != factors or (
                    annotator_id is not None and existing.annotator_id != annotator_id):
                raise HTTPException(409, detail=f"Task {label_id} changed after scoring")
            confidence = existing.confidence
            engine = await repository.load_engine(session, config.domain_id, existing.annotator_id)
            if engine is None:
                raise HTTPException(404, detail="Project engine not found")
            stats = await _category_stats(session, config.domain_id, engine.config.categories)
            status = evaluate_domain(engine, stats)[category]
            eligible = status.tier is AutonomyTier.AUTONOMOUS and status.conservation_gate_pass
        else:
            outcome = await _ingest(session, config.domain_id, IngestItem(
                label_id=label_id, category=category, annotator_id=annotator_id, factors=factors))
            confidence = outcome.confidence
            eligible = outcome.auto_accepted
        count, accuracy = await repository.verified_accuracy(session, config.domain_id, category, annotator_id) if annotator_id else (0, None)
        active_engine = await repository.load_engine(session, config.domain_id, annotator_id)
        gate_clear = bool(active_engine and active_engine.conservation.check_gate(active_engine.config.n_categories)[0])
        checks = {"project_autonomous": eligible, "annotator_verified_30": count >= 30,
                  "annotator_accuracy_80": accuracy is not None and accuracy >= .80,
                  "item_confidence_60": confidence >= .60,
                  "conservation_clear": gate_clear}
        allowed = all(checks.values())
        predictions.append({"result": [], "score": confidence if allowed else min(confidence * .49, .49),
                            "model_version": "jm-v1", "eligibility": {
                                "checks_passed": [name for name, passed in checks.items() if passed],
                                "checks_failed": [name for name, passed in checks.items() if not passed]}})
    return {"results": predictions}


@router.post("/webhook")
async def webhook(payload: dict[str, Any], session: Session, _: Authorized, tenant: Tenant) -> dict[str, str]:
    if payload.get("action") not in {"ANNOTATION_CREATED", "ANNOTATION_UPDATED"}:
        return {"status": "ignored"}
    config = _bind_config(_config(payload.get("project"), tenant), tenant)
    annotation = payload.get("annotation")
    if not isinstance(annotation, dict):
        raise HTTPException(422, detail="annotation is required")
    source_annotation_id = str(annotation.get("id", "")).strip()
    if not source_annotation_id:
        raise HTTPException(422, detail="annotation id is required")
    annotation_id = f"{config.project_id}:{source_annotation_id}"
    if len(annotation_id) > 200:
        raise HTTPException(422, detail="annotation id is too long")
    task = payload.get("task")
    if not isinstance(task, dict):
        task = {"id": annotation.get("task"), "data": payload.get("data", {})}
    label_id, category, factors = _task_values(task, config)
    actual = _action(annotation)
    await _ensure_domain(session, config)
    row = await session.scalar(select(LabelLog).where(
        LabelLog.domain_id == config.domain_id, LabelLog.tenant_id == tenant,
        LabelLog.annotation_id == annotation_id).order_by(LabelLog.scored_at, LabelLog.id).with_for_update())
    if row is None:
        row = await session.scalar(select(LabelLog).where(
            LabelLog.domain_id == config.domain_id, LabelLog.tenant_id == tenant,
            LabelLog.label_id == label_id).with_for_update())
        if row is not None and row.annotation_id is not None:
            row = None
    while row is not None and row.superseded_by is not None:
        row = await session.scalar(select(LabelLog).where(
            LabelLog.domain_id == config.domain_id, LabelLog.tenant_id == tenant,
            LabelLog.label_id == row.superseded_by).with_for_update())
    if row is None:
        ingest_id = "annotation:" + hashlib.sha256(
            f"{label_id}\0{annotation_id}".encode()).hexdigest()
        await _ingest(session, config.domain_id, IngestItem(
            label_id=ingest_id, category=category,
            annotator_id=str(annotation["completed_by"]) if annotation.get("completed_by") is not None else None,
            factors=factors))
        row = await session.scalar(select(LabelLog).where(
            LabelLog.domain_id == config.domain_id, LabelLog.tenant_id == tenant,
            LabelLog.label_id == ingest_id).with_for_update())
    assert row is not None
    row.annotation_id = annotation_id
    row.source_task_id = label_id
    if row.category != category or row.factors_json != factors:
        raise HTTPException(409, detail="Task changed after scoring")
    reviewer = (str(annotation["completed_by"])
                if annotation.get("completed_by") is not None else row.annotator_id)
    ground_truth = _field(task["data"], config.ground_truth_field) if config.ground_truth_field else None
    if ground_truth is None:
        return {"status": "pending_ground_truth"}
    if row.verified_at is None and reviewer is not None:
        row.annotator_id = reviewer
    correct = ground_truth == actual if isinstance(ground_truth, str) else ground_truth
    if not isinstance(correct, bool):
        raise HTTPException(422, detail="Ground truth must be an action or boolean")
    if row.verified_at is not None and (row.actual_action, row.verified_outcome, row.annotator_id) == (actual, correct, reviewer):
        return {"status": "processed"}
    if row.verified_at is not None and payload["action"] != "ANNOTATION_UPDATED":
        raise HTTPException(409, detail="Verification already exists")
    domain = await repository.get_domain(session, config.domain_id)
    assert domain is not None
    if actual not in domain.config_json["actions"]:
        raise HTTPException(422, detail="Unknown annotation action")
    if row.verified_at is None:
        engine = await repository.load_or_create_engine(session, config.domain_id, row.annotator_id)
        await repository.verify_and_learn(session, engine, config.domain_id, row.label_id, actual, correct)
        return {"status": "processed"}
    await repository.verify_and_relearn(session, config.domain_id, row, actual, correct, reviewer)
    return {"status": "processed"}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "UP", "model_version": "jm-v1"}
