"""Label Studio task adapter backed by the labeling repository."""
from __future__ import annotations

import json
import hashlib
import os
import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db import repository
from auth import Tenant, public_alias, scoped_domain_id
from db.connection import commit_write, get_db
from db.entitlement import resolve_entitlement
from db.models import ConnectorConfigRow, Domain, LabelContent, LabelLog, ProjectRequest
from db.tenant_lock import lock_tenant
from jm_core import DomainConfig, JudgmentMemoryEngine
from labeling_router import (EditableNerSpan, IngestItem, LabelContentRequest, _category_stats,
                             _ingest, prepare_content, validate_batch_media)
import modality
from modality import validate_layout
from policy_engine import AutonomyTier, evaluate_domain
from rate_limit import limiter

router = APIRouter(prefix="/v1/label-studio", tags=["Label Studio"])
logger = logging.getLogger(__name__)
Session = Annotated[AsyncSession, Depends(get_db)]
_default_map = {"model_confidence": "data.ml_confidence",
                "annotator_agreement": "data.agreement_score"}


def _authorize(token: Annotated[str | None, Header(alias="X-LS-Token")] = None) -> None:
    expected = os.getenv("LABEL_STUDIO_TOKEN")
    if not expected:
        raise HTTPException(503, detail="Label Studio token is not configured")
    if token is None or not compare_digest(token.encode(), expected.encode()):
        raise HTTPException(401, detail="Invalid Label Studio token")


Authorized = Annotated[None, Depends(_authorize)]


async def _admit_connector_media(request: Request, _: Authorized) -> None:
    """Bound self-identifying embedded images before looking up a tenant or field mapping."""
    try:
        envelope = await request.json()
    except (ValueError, RecursionError):
        raise HTTPException(422, "Invalid request body") from None
    # Field mappings are tenant data. Walk JSON values without copying containers
    # or using the Python call stack, then apply the actual mapping under its lock.
    levels: list[Iterator[Any]] = [iter((envelope,))]
    decoded_total = 0
    while levels:
        try:
            value = next(levels[-1])
        except StopIteration:
            levels.pop()
            continue
        if isinstance(value, dict):
            levels.append(iter(value.values()))
        elif isinstance(value, list):
            levels.append(iter(value))
        elif isinstance(value, str) and value[:11].lower() == "data:image/":
            size = modality.validate_data_uri(value)[1]
            decoded_total += size
            if decoded_total > modality.MAX_INLINE:
                raise HTTPException(413, "Embedded images exceed 10 MiB")


AdmittedMedia = Annotated[None, Depends(_admit_connector_media)]


class ConnectorConfig(BaseModel):
    tenant_id: str | None = None
    domain_id: str = Field(min_length=1, max_length=200)
    public_domain_id: str | None = Field(default=None, min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    factor_map: dict[str, str] = Field(min_length=2)
    image_field: str | None = Field(default=None, pattern=r"^data\..+", max_length=200)
    category_field: str = "data.category"
    ground_truth_field: str | None = "data.ground_truth"
    actions: list[str] = Field(default_factory=lambda: ["approve", "reject"],
                               min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_fields(self) -> ConnectorConfig:
        return _validate_config(self)


def _config_path() -> Path:
    return Path(os.getenv("LS_CONFIG_PATH", "/data/ls_config.json"))


def _validate_config(config: ConnectorConfig) -> ConnectorConfig:
    try:
        public_alias(config.domain_id)
    except ValueError as exc:
        raise HTTPException(422, "public names cannot be UUID format") from exc
    if (len(config.factor_map) > 20 or
            any(not name.strip() or len(name) > 200 or not field.startswith("data.")
                or not 5 < len(field) <= 200
                for name, field in config.factor_map.items())):
        raise HTTPException(422, detail="Factor names must be nonempty and mapped from data fields")
    if not config.category_field.startswith("data.") or len(config.category_field) > 200:
        raise HTTPException(422, detail="category_field must start with data.")
    if (config.ground_truth_field is not None and
            (not config.ground_truth_field.startswith("data.") or len(config.ground_truth_field) > 200)):
        raise HTTPException(422, detail="ground_truth_field must start with data.")
    if (any(not action.strip() or "|" in action or len(action) > 200 for action in config.actions)
            or len(set(config.actions)) != len(config.actions)):
        raise HTTPException(422, detail="Connector actions must be unique 1–200 character IDs")
    return config


def _saved_configs() -> dict[str, dict[str, Any]]:
    path = _config_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _external_id(value: Any, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise HTTPException(422, detail=f"{label} must be a string or integer")
    result = str(value).strip()
    if not result or len(result) > 200:
        raise HTTPException(422, detail=f"{label} must be 1–200 characters")
    return result


def _project_id(project: Any) -> str:
    value = project.get("id") if isinstance(project, dict) else project
    return _external_id(value, "Label Studio project ID")


async def _import_saved_configs(session: AsyncSession) -> None:
    """Import legacy configuration without overwriting any committed DB value."""
    marker = await session.get(ConnectorConfigRow, ("__legacy_import__", "__fence__"))
    if marker is not None:
        return
    saved = _saved_configs()
    dialect = session.get_bind().dialect.name
    for key, value in saved.items():
        if "\0" in key:
            tenant_id, project_id = key.split("\0", 1)
        else:
            tenant_id = str(value.get("tenant_id") or os.getenv("LABEL_STUDIO_TENANT_ID", ""))
            project_id = key
        if not tenant_id or not project_id:
            continue
        fields = dict(tenant_id=tenant_id, project_id=project_id, config_json=value, version=1)
        if dialect == "postgresql":
            pg_statement = pg_insert(ConnectorConfigRow).values(**fields).on_conflict_do_nothing(
                index_elements=[ConnectorConfigRow.tenant_id, ConnectorConfigRow.project_id])
            await session.execute(pg_statement)
        else:
            sqlite_statement = sqlite_insert(ConnectorConfigRow).values(**fields).on_conflict_do_nothing(
                index_elements=[ConnectorConfigRow.tenant_id, ConnectorConfigRow.project_id])
            await session.execute(sqlite_statement)
        if await session.get(ConnectorConfigRow, (tenant_id, project_id)) is None:
            raise HTTPException(503, detail="Connector configuration import did not complete")
    marker_values = dict(tenant_id="__legacy_import__", project_id="__fence__",
                         config_json={"complete": True}, version=1)
    if dialect == "postgresql":
        await session.execute(pg_insert(ConnectorConfigRow).values(**marker_values).on_conflict_do_nothing(
            index_elements=[ConnectorConfigRow.tenant_id, ConnectorConfigRow.project_id]))
    else:
        await session.execute(sqlite_insert(ConnectorConfigRow).values(**marker_values).on_conflict_do_nothing(
            index_elements=[ConnectorConfigRow.tenant_id, ConnectorConfigRow.project_id]))


async def _config(session: AsyncSession, project: Any, tenant: str | None = None) -> ConnectorConfig:
    project_id = _project_id(project)
    await _import_saved_configs(session)
    scope = tenant if tenant is not None else os.getenv("LABEL_STUDIO_TENANT_ID")
    if scope is not None:
        row = await session.get(ConnectorConfigRow, (scope, project_id))
        if row is not None:
            return ConnectorConfig.model_validate(row.config_json)
    mapping = json.loads(os.getenv("LS_FACTOR_MAP", json.dumps(_default_map)))
    domain_name = os.getenv("LABEL_STUDIO_DOMAIN_ID", f"ls-{project_id}")
    if not 0 < len(domain_name) <= 200:
        raise HTTPException(422, "Connector domain ID must be 1–200 characters")
    return ConnectorConfig(
        domain_id=domain_name,
        project_id=project_id, factor_map=mapping,
    )


def _bind_config(config: ConnectorConfig, tenant: str) -> ConnectorConfig:
    if config.tenant_id is not None and config.tenant_id != tenant:
        raise HTTPException(404, detail="Project not found")
    return config.model_copy(update={"domain_id": scoped_domain_id(tenant, config.domain_id),
                                      "public_domain_id": config.domain_id,
                                      "tenant_id": tenant})


def _field(data: dict[str, Any], path: str) -> Any:
    value: Any = {"data": data}
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _task_values(task: Any, config: ConnectorConfig, index: int | None = None) -> tuple[str, str, dict[str, float]]:
    if not isinstance(task, dict):
        raise HTTPException(422, detail=f"Task at index {index} must be an object")
    if task.get("id") is None or not isinstance(task.get("data"), dict):
        raise HTTPException(422, detail="Task requires id and data")
    data = task["data"]
    factors: dict[str, float] = {}
    for name, path in config.factor_map.items():
        value = _field(data, path)
        if value is None:
            value = 0.5
        if isinstance(value, bool):
            raise HTTPException(422, detail="Invalid task factor")
        try:
            factors[name] = float(value)
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(422, detail="Invalid task factor") from None
    category = _field(data, config.category_field) or "default"
    try:
        item = IngestItem(label_id=_external_id(task["id"], "Task ID"),
                          category=_external_id(category, "Category"), factors=factors,
                          annotator_id=(_external_id(task["annotator_id"], "Annotator ID")
                                        if task.get("annotator_id") is not None else None))
    except ValidationError:
        location = "" if index is None else f" at index {index}"
        raise HTTPException(422, f"Invalid task identifiers or factors{location}") from None
    return item.label_id, item.category, item.factors


def _mapped_content(task: dict[str, Any], config: ConnectorConfig) -> LabelContentRequest | None:
    value = _field(task["data"], config.image_field) if config.image_field else None
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(422, "Invalid image HTTPS URL")
    return LabelContentRequest(content_type="image_classification", image_url=value)


async def _check_bound_media(session: AsyncSession, domain: Domain, row: LabelLog,
                             supplied: LabelContentRequest | None) -> None:
    if supplied is None and not domain.modality_enforced:
        return
    layout = (await session.execute(select(
        LabelContent.content_type, LabelContent.image_url.is_not(None),
        LabelContent.image_url == (supplied.image_url if supplied else None)
    ).where(LabelContent.label_log_id == row.id))).one_or_none()
    if supplied and (layout is None or not layout[2]):
        raise HTTPException(409, "Task image changed after scoring")
    validate_layout(domain, layout[0] if layout else None, bool(layout and layout[1]))


async def _task_source(session: AsyncSession, domain: Domain, task_id: str,
                       supplied: LabelContentRequest | None) -> LabelContentRequest | None:
    """Re-use the source if a different annotation already bound this task."""
    if supplied is None and not (domain.modality_enforced and domain.content_type == "image"):
        return None
    previous = await session.scalar(select(LabelContent.image_url).join(
        LabelLog, LabelLog.id == LabelContent.label_log_id).where(
        LabelLog.domain_id == domain.domain_id, LabelLog.tenant_id == domain.tenant_id,
        LabelLog.source_task_id == task_id, LabelContent.content_type == "image_classification"
    ).limit(1))
    if previous is None:
        return supplied
    if supplied and supplied.image_url != previous:
        raise HTTPException(409, "Task image changed after scoring")
    return supplied or LabelContentRequest(content_type="image_classification", image_url=previous)


async def _ensure_domain(session: AsyncSession, config: ConnectorConfig) -> None:
    domain = await session.scalar(select(Domain).where(
        Domain.domain_id == config.domain_id,
        Domain.tenant_id == config.tenant_id).with_for_update()
        .execution_options(populate_existing=True))
    if domain is None:
        await repository.create_domain(session, config.domain_id, config.domain_id,
                                       DomainConfig(config.domain_id, config.domain_id,
                                                    list(config.factor_map), ["default"],
                                                    config.actions),
                                       public_domain_id=config.public_domain_id)
    else:
        if domain.status != "active":
            raise HTTPException(409, detail="Project is read-only")
        if set(domain.config_json["factors"]) != set(config.factor_map):
            raise HTTPException(409, detail="Configured factors differ from the existing domain")
        if domain.config_json["actions"] != config.actions:
            raise HTTPException(409, detail="Configured actions differ from the existing domain")


def _actions(annotation: dict[str, Any]) -> list[str]:
    selected: list[str] = []
    if "actual_action" in annotation:
        selected.append(_external_id(annotation["actual_action"], "Annotation action"))
    results = annotation.get("result", [])
    if not isinstance(results, list):
        raise HTTPException(422, "Invalid annotation result")
    for entry in results:
        if not isinstance(entry, dict) or not isinstance(entry.get("value"), dict):
            raise HTTPException(422, "Invalid annotation result")
        value = entry["value"]
        for field in ("choices", "labels", "rectanglelabels"):
            if field in value:
                if field == "labels" and "start" in value and "end" in value:
                    continue
                choices = value[field]
                if not isinstance(choices, list):
                    raise HTTPException(422, "Invalid annotation choices")
                for choice in choices:
                    candidate = _external_id(choice, "Annotation action")
                    selected.append(candidate)
    if not selected:
        raise HTTPException(422, "Annotation action is unavailable")
    return selected


def _spans(annotation: dict[str, Any]) -> list[EditableNerSpan] | None:
    raw = annotation.get("spans")
    if raw is None:
        results = annotation.get("result", [])
        raw = []
        for entry in results:
            if not isinstance(entry, dict) or not isinstance(entry.get("value"), dict):
                continue
            value = entry["value"]
            if "start" in value and "end" in value and "labels" in value:
                labels = value["labels"]
                if not isinstance(labels, list) or len(labels) != 1:
                    raise HTTPException(422, detail="Invalid annotation spans")
                raw.append({"start": value["start"], "end": value["end"],
                            "label": labels[0], "text": value.get("text")})
        if not raw:
            return None
    if not isinstance(raw, list) or len(raw) > 100:
        raise HTTPException(422, detail="Invalid annotation spans")
    try:
        return [EditableNerSpan.model_validate(value) for value in raw]
    except ValidationError as exc:
        raise HTTPException(422, detail="Invalid annotation spans") from exc


def _source_timestamp(annotation: dict[str, Any]) -> datetime | None:
    raw = annotation.get("updated_at") or annotation.get("created_at")
    if raw is None:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("timezone required")
        return stamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise HTTPException(422, detail="Invalid annotation timestamp") from None


class WebhookEnvelope(BaseModel, extra="allow"):
    @model_validator(mode="before")
    @classmethod
    def validate_dispatch(cls, payload: Any) -> Any:
        if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
            raise HTTPException(422, "action must be a string")
        if payload["action"] in {"ANNOTATION_CREATED", "ANNOTATION_UPDATED"}:
            project_id = _project_id(payload.get("project"))
            annotation = payload.get("annotation")
            if not isinstance(annotation, dict):
                raise HTTPException(422, "annotation is required")
            annotation_id = _external_id(annotation.get("id"), "Annotation ID")
            _external_id(f"{project_id}:{annotation_id}", "Composite annotation ID")
            if annotation.get("completed_by") is not None:
                _external_id(annotation["completed_by"], "Annotator ID")
            _actions(annotation)
            _spans(annotation)
            _source_timestamp(annotation)
            task = payload.get("task", {"id": annotation.get("task"), "data": payload.get("data", {})})
            if not isinstance(task, dict) or not isinstance(task.get("data"), dict):
                raise HTTPException(422, "Task requires id and data")
            _external_id(task.get("id"), "Task ID")
        return payload


@router.post("/configure")
async def configure(config: ConnectorConfig, session: Session, _: Authorized, tenant: Tenant,
                    response: Response,
                    if_match: Annotated[str | None, Header(alias="If-Match")] = None
                    ) -> ConnectorConfig:
    expected_version = None
    if if_match is not None:
        try:
            expected_version = int(if_match.strip('"'))
        except ValueError:
            raise HTTPException(422, detail="Invalid connector version") from None
    config = config.model_copy(update={"tenant_id": tenant})
    await lock_tenant(session, tenant)
    await resolve_entitlement(tenant, session, for_update=True, purpose="write")
    bound = await repository.get_domain(session, scoped_domain_id(tenant, config.domain_id), tenant)
    if bound is not None and bound.status != "active":
        raise HTTPException(409, detail="Project is read-only")
    await _import_saved_configs(session)
    for _attempt in range(3):
        row = await session.get(ConnectorConfigRow, (tenant, config.project_id),
                                with_for_update=True, populate_existing=True)
        version = row.version if row is not None else 0
        if expected_version is not None and expected_version != version:
            raise HTTPException(409, detail="Connector configuration changed; retry")
        if row is not None and row.config_json.get("domain_id") != config.domain_id:
            raise HTTPException(409, detail="Connector project is already bound to a different domain")
        if row is None:
            dialect = session.get_bind().dialect.name
            fields = dict(tenant_id=tenant, project_id=config.project_id,
                          config_json=config.model_dump(), version=1)
            if dialect == "postgresql":
                pg_statement = pg_insert(ConnectorConfigRow).values(**fields).on_conflict_do_nothing(
                    index_elements=[ConnectorConfigRow.tenant_id, ConnectorConfigRow.project_id])
                result = await session.execute(pg_statement)
            else:
                sqlite_statement = sqlite_insert(ConnectorConfigRow).values(**fields).on_conflict_do_nothing(
                    index_elements=[ConnectorConfigRow.tenant_id, ConnectorConfigRow.project_id])
                result = await session.execute(sqlite_statement)
            if getattr(result, "rowcount", None) == 1:
                break
        else:
            result = await session.execute(update(ConnectorConfigRow).where(
                ConnectorConfigRow.tenant_id == tenant,
                ConnectorConfigRow.project_id == config.project_id,
                ConnectorConfigRow.version == row.version).values(
                    config_json=config.model_dump(), version=row.version + 1))
            if getattr(result, "rowcount", None) == 1:
                break
        session.expire_all()
    else:
        raise HTTPException(409, detail="Connector configuration changed; retry")
    await commit_write(session)
    response.headers['ETag'] = f'"{version + 1}"'
    return config


@router.post("/setup")
async def setup(payload: dict[str, Any], session: Session, _: Authorized) -> dict[str, str]:
    setup_tenant = os.getenv("LABEL_STUDIO_TENANT_ID")
    if setup_tenant:
        await lock_tenant(session, setup_tenant)
    config = await _config(session, payload.get("project"), setup_tenant)
    setup_tenant = config.tenant_id or setup_tenant
    if setup_tenant:
        await lock_tenant(session, setup_tenant)
        session.info["tenant_id"] = setup_tenant
        await resolve_entitlement(setup_tenant, session, for_update=True,
                                  service_token=True, purpose="write")
        await _ensure_domain(session, _bind_config(config, setup_tenant))
        await commit_write(session)
    return {"model_version": "jm-v1"}


class PredictionEnvelope(BaseModel):
    project: Any
    tasks: list[dict[str, Any]]

    @field_validator("tasks", mode="before")
    @classmethod
    def validate_task_objects(cls, tasks: Any) -> Any:
        if not isinstance(tasks, list):
            raise HTTPException(422, "tasks must be a list")
        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                raise HTTPException(422, f"Task at index {index} must be an object")
        return tasks

    @model_validator(mode="after")
    def validate_tasks(self) -> PredictionEnvelope:
        _project_id(self.project)
        for task in self.tasks:
            _external_id(task.get("id"), "Task ID")
            if not isinstance(task.get("data"), dict):
                raise HTTPException(422, "Task requires id and data")
            if task.get("annotator_id") is not None:
                _external_id(task["annotator_id"], "Annotator ID")
        return self


@router.post("/predict")
async def predict(payload: PredictionEnvelope, response: Response, session: Session, _: AdmittedMedia,
                  tenant: Tenant) -> dict[str, list[dict[str, Any]]]:
    await lock_tenant(session, tenant)
    config = _bind_config(await _config(session, payload.project, tenant), tenant)
    tasks = payload.tasks
    prepared: list[IngestItem] = []
    for index, task in enumerate(tasks):
        label_id, category, factors = _task_values(task, config, index)
        prepared.append(IngestItem(label_id=label_id, category=category, factors=factors,
                                   annotator_id=(_external_id(task["annotator_id"], "Annotator ID")
                                                 if task.get("annotator_id") is not None else None),
                                   content=_mapped_content(task, config)))
    validate_batch_media(prepared)
    await resolve_entitlement(tenant, session, for_update=True, purpose="write")
    await _ensure_domain(session, config)
    predictions: list[dict[str, Any]] = []
    domain = await repository.get_domain(session, config.domain_id)
    assert domain is not None
    existing_rows: dict[str, LabelLog] = {}
    ids = list({item.label_id for item in prepared})
    for start in range(0, len(ids), 500):
        rows = await session.scalars(select(LabelLog).where(
            LabelLog.domain_id == config.domain_id, LabelLog.tenant_id == tenant,
            LabelLog.label_id.in_(ids[start:start + 500])))
        existing_rows.update((row.label_id, row) for row in rows)
    for index, item in enumerate(prepared):
        existing = existing_rows.get(item.label_id)
        if existing is None:
            prepare_content(domain, item, {item.category}, index)
            if item.content is not None:
                await _task_source(session, domain, item.label_id, item.content)
    for item in prepared:
        label_id, category, factors, annotator_id = item.label_id, item.category, item.factors, item.annotator_id
        existing = existing_rows.get(label_id)
        if existing is not None:
            await _check_bound_media(session, domain, existing, item.content)
            if existing.scored_at is None or existing.confidence is None:
                raise HTTPException(409, detail="Task is awaiting classification")
            if existing.category != category or existing.factors_json != factors or (
                    annotator_id is not None and existing.annotator_id != annotator_id):
                raise HTTPException(409, detail="Task changed after scoring")
            confidence = existing.confidence
            engine = await repository.load_engine(session, config.domain_id, existing.annotator_id)
            if engine is None:
                raise HTTPException(404, detail="Project engine not found")
            stats = await _category_stats(session, config.domain_id, engine.config.categories)
            status = evaluate_domain(engine, stats)[category]
            eligible = status.tier is AutonomyTier.AUTONOMOUS and status.conservation_gate_pass
        else:
            outcome = await _ingest(session, config.domain_id, item, config.public_domain_id)
            saved = await session.scalar(select(LabelLog).where(
                LabelLog.domain_id == config.domain_id, LabelLog.tenant_id == tenant,
                LabelLog.label_id == label_id))
            assert saved is not None
            existing_rows[label_id] = saved
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
    if warning := session.info.get("volume_warning"):
        response.headers["X-Volume-Warning"] = warning
    await commit_write(session)
    return {"results": predictions}


@router.post("/webhook")
async def webhook(envelope: WebhookEnvelope, session: Session, _: AdmittedMedia, tenant: Tenant) -> dict[str, str]:
    payload = envelope.model_dump()
    action = payload.get("action")
    if not isinstance(action, str):
        raise HTTPException(422, detail=f"action must be a string, got {type(action).__name__}")
    if action not in {"ANNOTATION_CREATED", "ANNOTATION_UPDATED"}:
        return {"status": "ignored"}
    annotation = payload.get("annotation")
    if not isinstance(annotation, dict):
        raise HTTPException(422, detail="annotation is required")
    raw_annotation_id = annotation.get("id")
    source_annotation_id = _external_id(raw_annotation_id, "Annotation ID")
    source_time = _source_timestamp(annotation)
    task = payload.get("task")
    if not isinstance(task, dict):
        task = {"id": annotation.get("task"), "data": payload.get("data", {})}
    try:
        actions = _actions(annotation)
        actual = actions[0]
    except (TypeError, AttributeError, KeyError):
        raise HTTPException(422, detail="Invalid annotation result") from None
    requested_spans = _spans(annotation)
    if annotation.get("completed_by") is not None:
        _external_id(annotation["completed_by"], "Annotator ID")
    await lock_tenant(session, tenant)
    config = _bind_config(await _config(session, payload.get("project"), tenant), tenant)
    # The readable legacy form has an unambiguous first separator unless
    # the project ID itself contains a colon. The digest form has no colon.
    annotation_id = (hashlib.sha256(json.dumps([config.project_id, source_annotation_id],
                                               separators=(",", ":")).encode()).hexdigest()
                     if ":" in config.project_id else f"{config.project_id}:{source_annotation_id}")
    if len(annotation_id) > 200:
        raise HTTPException(422, detail="annotation id is too long")
    label_id, category, factors = _task_values(task, config)
    mapped_content = _mapped_content(task, config)
    ground_truth = _field(task["data"], config.ground_truth_field) if config.ground_truth_field else None
    if ground_truth is not None and not isinstance(ground_truth, (str, bool)):
        raise HTTPException(422, detail="Ground truth must be an action or boolean")
    if isinstance(ground_truth, str):
        ground_truth = _external_id(ground_truth, "Ground truth action")
    if any(action not in config.actions for action in actions):
        raise HTTPException(422, "Action is not in domain schema")
    if isinstance(ground_truth, str) and ground_truth not in config.actions:
        raise HTTPException(422, "Ground truth action is not in domain schema")
    # The tenant guard stabilizes this read through subsequent payer and label locks.
    bound_task = await session.scalar(select(LabelLog.source_task_id).where(
        LabelLog.tenant_id == tenant, LabelLog.domain_id == config.domain_id,
        LabelLog.annotation_id == annotation_id, LabelLog.source_task_id.is_not(None)).limit(1))
    if bound_task is not None and bound_task != label_id:
        raise HTTPException(409, detail="Annotation is bound to another task")
    await resolve_entitlement(tenant, session, for_update=True, purpose="write")
    await _ensure_domain(session, config)
    domain = await repository.get_domain(session, config.domain_id)
    assert domain is not None
    actor_key_id = session.info.get("actor_key_id") or session.info.get("payer_key_id")
    assert actor_key_id is not None
    payload_digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str,
                                               separators=(",", ":")).encode()).hexdigest()
    receipt_key = hashlib.sha256(f"{annotation_id}\0{source_time or payload_digest}".encode()).hexdigest()
    receipt_identity = (domain.id, actor_key_id, "connector_webhook", receipt_key)
    receipt = await session.get(ProjectRequest, receipt_identity, with_for_update=True)
    if receipt is not None:
        if receipt.payload_digest != payload_digest:
            raise HTTPException(409, detail="Conflicting connector delivery")
        return dict(receipt.result_json)

    async def finish(status: str) -> dict[str, str]:
        result = {"status": status}
        session.add(ProjectRequest(project_id=domain.id, actor_key_id=actor_key_id,
                                   operation="connector_webhook", request_key=receipt_key,
                                   payload_digest=payload_digest, result_json=result,
                                   expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
        await commit_write(session)
        return result

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
    if row is not None and row.source_task_id is not None and row.source_task_id != label_id:
        raise HTTPException(409, detail="Annotation is bound to another task")
    if row is not None:
        await _check_bound_media(session, domain, row, mapped_content)
    if row is not None and source_time is None and row.source_updated_at is not None:
        raise HTTPException(409, detail="Undated connector correction is ambiguous")
    if row is not None and source_time is not None and row.source_updated_at is not None:
        stored = row.source_updated_at
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=timezone.utc)
        if source_time <= stored:
            return await finish("processed")
    if row is None:
        mapped_content = await _task_source(session, domain, label_id, mapped_content)
        ingest_id = "annotation:" + hashlib.sha256(
            f"{label_id}\0{annotation_id}".encode()).hexdigest()
        try:
            item = IngestItem(
                label_id=ingest_id, category=category,
                annotator_id=_external_id(annotation["completed_by"], "Annotator ID") if annotation.get("completed_by") is not None else None,
                factors=factors, content=mapped_content)
        except ValidationError as exc:
            raise HTTPException(422, detail="Invalid task at index 0") from exc
        await _ingest(session, config.domain_id, item, config.public_domain_id)
        row = await session.scalar(select(LabelLog).where(
            LabelLog.domain_id == config.domain_id, LabelLog.tenant_id == tenant,
            LabelLog.label_id == ingest_id).with_for_update())
    assert row is not None
    prediction = await repository.prediction_for_revision(session, row.id)
    if prediction is not None and prediction.state == "human_reviewed" and row.verified_at is None:
        raise HTTPException(409, detail="Reopen the reviewed prediction before verifying it")
    row.annotation_id = annotation_id
    row.source_task_id = label_id
    if row.category != category or row.factors_json != factors:
        raise HTTPException(409, detail="Task changed after scoring")
    edited_spans: list[dict[str, Any]] | None = None
    current_spans: list[dict] | None = None
    if requested_spans is not None:
        existing_content = await repository.get_label_content(session, row.id)
        if existing_content is None or existing_content.content_type != "text_ner" or row.text is None:
            raise HTTPException(422, detail="NER spans require stored NER text")
        current_spans = existing_content.spans_json
        edited_spans = []
        previous_end = 0
        for span in sorted(requested_spans, key=lambda value: (value.start, value.end)):
            if (span.label not in domain.config_json["categories"] or span.start < previous_end or
                    span.start >= span.end or span.end > len(row.text) or
                    (span.text is not None and row.text[span.start:span.end] != span.text)):
                raise HTTPException(422, detail="Invalid annotation span offsets")
            edited_spans.append({"start": span.start, "end": span.end,
                                 "label": span.label, "text": row.text[span.start:span.end]})
            previous_end = span.end
    reviewer = (_external_id(annotation["completed_by"], "Annotator ID")
                if annotation.get("completed_by") is not None else row.annotator_id)
    if row.verified_at is None and edited_spans is not None:
        assert existing_content is not None
        existing_content.spans_json = edited_spans
        if prediction is not None and ground_truth is None and current_spans != edited_spans:
            if prediction.state != "pending":
                raise HTTPException(409, detail="Reopen prediction before editing")
            prediction.decision_version += 1
    if ground_truth is None:
        if source_time is not None:
            row.source_updated_at = source_time
        return await finish("pending_ground_truth")
    if row.verified_at is None and reviewer is not None:
        row.annotator_id = reviewer
    correct = ground_truth == actual if isinstance(ground_truth, str) else ground_truth
    if not isinstance(correct, bool):
        raise HTTPException(422, detail="Ground truth must be an action or boolean")
    if row.verified_at is not None and (source_time is None or row.source_updated_at is None):
        seen = await session.scalar(select(LabelLog.id).where(
            LabelLog.domain_id == config.domain_id, LabelLog.tenant_id == tenant,
            LabelLog.annotation_id == annotation_id, LabelLog.id != row.id,
            LabelLog.actual_action == actual, LabelLog.verified_outcome == correct,
            LabelLog.annotator_id == reviewer).limit(1))
        if seen is not None:
            return await finish("processed")
    if (row.verified_at is not None and
            (row.actual_action, row.verified_outcome, row.annotator_id) == (actual, correct, reviewer) and
            (edited_spans is None or edited_spans == current_spans)):
        if source_time is not None:
            row.source_updated_at = source_time
        return await finish("processed")
    if row.verified_at is not None and payload["action"] != "ANNOTATION_UPDATED":
        raise HTTPException(409, detail="Verification already exists")
    if actual not in domain.config_json["actions"]:
        raise HTTPException(422, detail="Unknown annotation action")
    if row.verified_at is None:
        engine = await repository.load_or_create_engine(session, config.domain_id, row.annotator_id)
        if row.category not in domain.config_json["categories"]:
            raise HTTPException(422, detail="Category not in domain schema")
        repository.sync_engine_categories(engine, domain.config_json["categories"])
        await repository.verify_and_learn(session, engine, config.domain_id, row.label_id, actual, correct)
        if prediction is not None:
            repository.record_unassessed_prediction_review(prediction, row)
        await repository.record_webhook_event(session, domain, "label.verified", str(row.id), {
            "label_id": row.label_id, "revision_id": str(row.id),
            "actual_action": actual, "verified_outcome": correct,
            "source": "label_studio", "source_task_id": row.source_task_id,
        })
        row.source_updated_at = source_time
        return await finish("processed")
    await repository.verify_and_relearn(session, config.domain_id, row, actual, correct, reviewer)
    successor = await session.scalar(select(LabelLog).where(
        LabelLog.domain_id == config.domain_id, LabelLog.tenant_id == tenant,
        LabelLog.label_id == row.superseded_by))
    assert successor is not None
    successor.source_updated_at = source_time
    if prediction is not None:
        repository.record_unassessed_prediction_review(prediction, successor)
    await repository.record_webhook_event(session, domain, "label.verified", str(successor.id), {
        "label_id": successor.label_id, "revision_id": str(successor.id),
        "actual_action": actual, "verified_outcome": correct,
        "source": "label_studio", "source_task_id": successor.source_task_id,
    })
    if edited_spans is not None:
        successor_content = await repository.get_label_content(session, successor.id)
        assert successor_content is not None
        successor_content.spans_json = edited_spans
    return await finish("processed")


@router.get("/health")
@limiter.limit("60/minute")
async def health(request: Request) -> dict[str, str]:
    return {"status": "UP", "model_version": "jm-v1"}
