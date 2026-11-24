"""Core labeling routes backed by the async persistence repository."""
from __future__ import annotations

from dataclasses import asdict
import json
from math import isfinite
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from db.connection import get_db
from db.models import LabelLog
from db import repository
from auth import Tenant, scoped_domain_id
from jm_core import ConservationState, DomainConfig, JudgmentMemoryEngine
from policy_engine import AutonomyTier, evaluate_domain
from rate_limit import limiter
from trial_guard import reserve_label_capacity

router = APIRouter(prefix="/v1/labels", tags=["Labeling"])
autonomy_router = APIRouter(prefix="/v1/domains", tags=["Labeling"])
Session = Annotated[AsyncSession, Depends(get_db)]


class IngestItem(BaseModel):
    label_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    annotator_id: str | None = None
    factors: dict[str, float] = Field(min_length=2)
    text: str | None = None

    @field_validator("text")
    @classmethod
    def valid_text(cls, value: str | None) -> str | None:
        if value == "":
            return None
        if value is not None:
            try:
                size = len(value.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise ValueError("text must be valid UTF-8") from exc
            if size > 32 * 1024:
                raise ValueError("text must be at most 32 KiB UTF-8")
        return value

    @field_validator("label_id", "category", "annotator_id")
    @classmethod
    def valid_identifier(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "|" in value):
            raise ValueError("Identifiers must be nonempty and cannot contain |")
        return value

    @field_validator("factors")
    @classmethod
    def valid_factors(cls, factors: dict[str, float]) -> dict[str, float]:
        if any(not name.strip() or not isfinite(value) or not 0 <= value <= 1
               for name, value in factors.items()):
            raise ValueError("Factor names must be nonempty and values finite in [0, 1]")
        return factors


class IngestRequest(IngestItem):
    domain_id: str = Field(min_length=1)


class IngestResponse(BaseModel):
    label_id: str
    decision_id: str
    recommended_action: str
    confidence: float
    factors_used: dict[str, float]
    category: str
    conservation_status: str
    tier: str
    action_policy: str
    tier_status: dict
    auto_accepted: bool


class VerifyRequest(BaseModel):
    domain_id: str = Field(min_length=1)
    label_id: str = Field(min_length=1)
    actual_action: str = Field(min_length=1)
    verified_outcome: bool
    annotator_id: str | None = None


class VerifyResponse(BaseModel):
    label_id: str
    action_taken: str
    was_correct: bool
    engine_updated: bool
    new_accuracy: float | None


class IngestBatchRequest(BaseModel):
    domain_id: str = Field(min_length=1)
    items: list[IngestItem] = Field(min_length=1, max_length=100)


class IngestBatchResponse(BaseModel):
    results: list[IngestResponse]
    batch_size: int


SAMPLE_DOMAIN = "medical-ner-demo-v1"
SAMPLE_MARKER = "DLJ sample: medical-ner-demo-v1"


def _sample_items() -> list[IngestItem]:
    root = Path(__file__).resolve().parent / "frontend"
    fixture = root / "dist" / "demo" / "sample_data.json"
    if not fixture.is_file():
        fixture = root / "public" / "demo" / "sample_data.json"
    try:
        data = json.loads(fixture.read_text(encoding="utf-8"))
        if data["domain_id"] != SAMPLE_DOMAIN or len(data["rows"]) != 500:
            raise ValueError("Unexpected sample fixture")
        rows = data["rows"][::41][:12]
        return [IngestItem(
            label_id=row["label_id"], category=row["category"],
            annotator_id=row["annotator_id"],
            text=row["text"],
            factors={"model_confidence": row["factor_model_confidence"],
                     "item_difficulty": row["factor_item_difficulty"]},
        ) for row in rows]
    except (OSError, KeyError, ValueError) as exc:
        raise HTTPException(503, detail="Sample fixture unavailable") from exc


async def _category_stats(session: AsyncSession, domain_id: str,
                          categories: list[str]) -> dict[str, dict]:
    rows = (await session.scalars(
        select(LabelLog).where(LabelLog.domain_id == domain_id,
                               LabelLog.tenant_id == session.info.get("tenant_id", ""),
                               LabelLog.superseded_by.is_(None),
                               LabelLog.verified_at.is_not(None),
                               LabelLog.verified_outcome.is_not(None))
        .order_by(LabelLog.verified_at, LabelLog.scored_at, LabelLog.id)
    )).all()
    outcomes: dict[str, list[bool]] = {category: [] for category in categories}
    for row in rows:
        if row.category in outcomes:
            outcomes[row.category].append(bool(row.verified_outcome))
    stats: dict[str, dict] = {}
    for category, values in outcomes.items():
        gate = ConservationState()
        for correct in values:
            gate.update(correct, category)
        passed, reason = gate.check_gate(1)
        stats[category] = {
            "verified_count": len(values),
            "accuracy": sum(values) / len(values) if values else None,
            "rolling_accuracy": sum(values[-50:]) / min(len(values), 50) if values else None,
            "conservation_gate_pass": passed,
            "conservation_reason": reason if reason != "clear" else None,
        }
    return stats


async def _prepare_engine(session: AsyncSession, domain_id: str,
                          item: IngestItem, public_domain_id: str | None = None) -> JudgmentMemoryEngine:
    domain = await repository.get_domain(session, domain_id)
    if domain is None:
        config = DomainConfig(domain_id, domain_id, list(item.factors), [item.category],
                              ["approve", "reject"])
        await repository.create_domain(session, domain_id, domain_id, config,
                                       public_domain_id=public_domain_id)
    else:
        if domain.public_domain_id is None and public_domain_id is not None:
            domain.public_domain_id = public_domain_id
        config = DomainConfig.from_dict(domain.config_json)
        if set(item.factors) != set(config.factors):
            raise HTTPException(status_code=422, detail="Factor names differ from the domain schema")
        if item.category not in config.categories:
            # Refresh under lock so concurrent PostgreSQL additions keep each other's categories.
            await session.refresh(domain, with_for_update=True)
            config = DomainConfig.from_dict(domain.config_json)
            if item.category not in config.categories:
                if len(config.categories) >= 20:
                    raise HTTPException(status_code=422, detail="Domain has reached 20 categories")
                config.categories = [*config.categories, item.category]
                domain.config_json = {**domain.config_json, "categories": config.categories}
    engine = await repository.load_or_create_engine(session, domain_id, item.annotator_id)
    for category in config.categories:
        if category not in engine.config.categories:
            engine.config.categories.append(category)
            for action in engine.config.actions:
                engine.centroids[f"{category}|{action}"] = [0.5] * engine.config.n_factors
    return engine


async def _ingest(session: AsyncSession, domain_id: str, item: IngestItem,
                  public_domain_id: str | None = None) -> IngestResponse:
    engine = await _prepare_engine(session, domain_id, item, public_domain_id)
    await reserve_label_capacity(session)
    result = await repository.score_and_persist(
        session, engine, domain_id, item.label_id, item.annotator_id,
        item.category, item.factors, item.text
    )
    stats = await _category_stats(session, domain_id, engine.config.categories)
    status = evaluate_domain(engine, stats)[item.category]
    auto_accepted = status.tier is AutonomyTier.AUTONOMOUS and status.conservation_gate_pass
    if auto_accepted and item.annotator_id is not None:
        count, accuracy = await repository.verified_accuracy(
            session, domain_id, item.category, item.annotator_id
        )
        auto_accepted = count >= 30 and accuracy is not None and accuracy >= 0.80
    return IngestResponse(
        label_id=item.label_id, decision_id=result.decision_id,
        recommended_action=result.recommended_action, confidence=result.confidence,
        factors_used=item.factors, category=item.category,
        conservation_status="paused" if result.gate_status.startswith("PAUSED") else result.gate_status,
        tier=status.tier.value, action_policy=status.recommended_action_policy,
        tier_status=asdict(status),
        auto_accepted=auto_accepted,
    )


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest, response: Response, session: Session, tenant: Tenant) -> IngestResponse:
    try:
        result = await _ingest(session, scoped_domain_id(tenant, request.domain_id), request,
                               request.domain_id)
        if warning := session.info.get("volume_warning"):
            response.headers["X-Volume-Warning"] = warning
        return result
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Domain or label already exists") from exc
    except StaleDataError as exc:
        raise HTTPException(status_code=409, detail="Engine state changed; retry") from exc


@router.post("/verify", response_model=VerifyResponse)
async def verify(request: VerifyRequest, session: Session, tenant: Tenant) -> VerifyResponse:
    domain_id = scoped_domain_id(tenant, request.domain_id)
    row = await session.scalar(select(LabelLog).where(LabelLog.domain_id == domain_id,
                                                     LabelLog.tenant_id == tenant,
                                                     LabelLog.label_id == request.label_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Label not found")
    if row.verified_at is not None:
        raise HTTPException(status_code=409, detail="Label already verified")
    if request.annotator_id is not None:
        if not request.annotator_id.strip():
            raise HTTPException(status_code=422, detail="annotator_id must be nonempty")
        row.annotator_id = request.annotator_id
    engine = await repository.load_engine(session, domain_id, row.annotator_id)
    if engine is None:
        engine = await repository.load_or_create_engine(session, domain_id, row.annotator_id)
    if request.actual_action not in engine.config.actions:
        raise HTTPException(status_code=422, detail="Unknown actual_action")
    try:
        result = await repository.verify_and_learn(
            session, engine, domain_id, request.label_id,
            request.actual_action, request.verified_outcome
        )
    except StaleDataError as exc:
        raise HTTPException(status_code=409, detail="Engine state changed; retry") from exc
    _, accuracy = await repository.verified_accuracy(session, domain_id, row.category)
    return VerifyResponse(label_id=request.label_id, action_taken=request.actual_action,
                          was_correct=request.verified_outcome,
                          engine_updated=result.centroid_moved, new_accuracy=accuracy)


@router.post("/ingest/batch", response_model=IngestBatchResponse)
async def ingest_batch(request: IngestBatchRequest, response: Response, session: Session,
                       tenant: Tenant) -> IngestBatchResponse:
    results: list[IngestResponse] = []
    for index, item in enumerate(request.items):
        try:
            results.append(await _ingest(session, scoped_domain_id(tenant, request.domain_id), item,
                                         request.domain_id))
        except (HTTPException, IntegrityError, StaleDataError, ValueError) as exc:
            if isinstance(exc, HTTPException) and exc.status_code in {402, 429}:
                raise
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            raise HTTPException(status_code=422, detail={"item_index": index, "error": detail}) from exc
    if warning := session.info.get("volume_warning"):
        response.headers["X-Volume-Warning"] = warning
    return IngestBatchResponse(results=results, batch_size=len(results))


@router.post("/{domain_id}/sample")
async def seed_sample(domain_id: str, response: Response, session: Session, tenant: Tenant) -> dict[str, str | int]:
    if domain_id != SAMPLE_DOMAIN:
        raise HTTPException(404, detail="Sample domain not found")
    items = _sample_items()
    scoped = scoped_domain_id(tenant, domain_id)
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:scope))"), {"scope": scoped})
    domain = await repository.get_domain(session, scoped)
    if domain is not None and domain.domain_name != SAMPLE_MARKER:
        raise HTTPException(409, detail="Domain name is already in use")
    ids = [item.label_id for item in items]
    existing_ids = set((await session.scalars(select(LabelLog.label_id).where(
        LabelLog.domain_id == scoped, LabelLog.tenant_id == tenant,
        LabelLog.label_id.in_(ids)))).all())
    if existing_ids:
        existing_rows = (await session.scalars(select(LabelLog).where(
            LabelLog.domain_id == scoped, LabelLog.tenant_id == tenant,
            LabelLog.label_id.in_(existing_ids)))).all()
        fixture_text = {item.label_id: item.text for item in items}
        for row in existing_rows:
            if row.text is None:
                row.text = fixture_text[row.label_id]
    created = 0
    for item in items:
        if item.label_id not in existing_ids:
            try:
                await _ingest(session, scoped, item, domain_id)
            except (IntegrityError, StaleDataError) as exc:
                raise HTTPException(409, detail="Sample seed conflicted; retry") from exc
            created += 1
            if domain is None:
                domain = await repository.get_domain(session, scoped)
                assert domain is not None
                domain.domain_name = SAMPLE_MARKER
    pending_ids = (await session.scalars(select(LabelLog.label_id).where(
        LabelLog.domain_id == scoped, LabelLog.tenant_id == tenant,
        LabelLog.label_id.in_(ids), LabelLog.verified_at.is_(None)))).all()
    if warning := session.info.get("volume_warning"):
        response.headers["X-Volume-Warning"] = warning
    return {"domain_id": domain_id, "created": created,
            "existing": len(existing_ids), "pending": len(pending_ids)}


@router.get("/{domain_id}/pending")
@limiter.limit("60/minute")
async def pending(request: Request, domain_id: str, response: Response, session: Session, tenant: Tenant,
                  category: str | None = None, limit: int = Query(default=50, ge=1, le=200),
                  offset: int = Query(default=0, ge=0),
                  sort_by: Literal["label_id", "category", "annotator_id", "confidence", "recommended_action"] | None = None,
                  sort_order: Literal["asc", "desc"] = "asc") -> list[dict]:
    domain_id = scoped_domain_id(tenant, domain_id)
    if await repository.get_domain(session, domain_id) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    filters = [LabelLog.domain_id == domain_id, LabelLog.tenant_id == tenant,
               LabelLog.verified_at.is_(None)]
    if category is not None:
        filters.append(LabelLog.category == category)
    total = await session.scalar(select(func.count()).select_from(LabelLog).where(*filters))
    response.headers["X-Total-Count"] = str(total or 0)
    query = select(LabelLog).where(*filters)
    if sort_by is None:
        query = query.order_by(LabelLog.confidence.asc(), LabelLog.scored_at.asc(), LabelLog.id.asc())
    else:
        column = getattr(LabelLog, sort_by)
        ordered = column.desc() if sort_order == "desc" else column.asc()
        query = query.order_by(ordered.nulls_last(), LabelLog.scored_at.asc(), LabelLog.id.asc())
    query = query.offset(offset).limit(limit)
    rows = (await session.scalars(query)).all()
    return [{"label_id": row.label_id, "category": row.category,
             "annotator_id": row.annotator_id, "confidence": row.confidence,
             "recommended_action": row.recommended_action, "factors": row.factors_json,
             "text_preview": row.text[:80] if row.text is not None else None}
            for row in rows]


@router.get("/{domain_id}/{label_id}")
@limiter.limit("60/minute")
async def label_detail(request: Request, domain_id: str, label_id: str,
                       session: Session, tenant: Tenant) -> dict:
    row = await session.scalar(select(LabelLog).where(
        LabelLog.domain_id == scoped_domain_id(tenant, domain_id),
        LabelLog.tenant_id == tenant, LabelLog.label_id == label_id))
    if row is None:
        raise HTTPException(404, detail="Label not found")
    return {"domain_id": domain_id, "label_id": row.label_id, "category": row.category,
            "annotator_id": row.annotator_id, "factors": row.factors_json,
            "recommended_action": row.recommended_action, "confidence": row.confidence,
            "text": row.text, "actual_action": row.actual_action,
            "verified_outcome": row.verified_outcome,
            "verified_at": row.verified_at.isoformat() if row.verified_at else None}


@autonomy_router.get("/{domain_id}/autonomy")
@limiter.limit("60/minute")
async def domain_autonomy(request: Request, domain_id: str, session: Session, tenant: Tenant) -> dict:
    public_domain_id = domain_id
    domain_id = scoped_domain_id(tenant, domain_id)
    domain = await repository.get_domain(session, domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    engine = await repository.load_or_create_engine(session, domain_id)
    categories = DomainConfig.from_dict(domain.config_json).categories
    for category in categories:
        if category not in engine.config.categories:
            engine.config.categories.append(category)
    stats = await _category_stats(session, domain_id, categories)
    statuses = evaluate_domain(engine, stats)
    rank = {AutonomyTier.RED: 0, AutonomyTier.AMBER: 1,
            AutonomyTier.GREEN: 2, AutonomyTier.AUTONOMOUS: 3}
    overall = min((status.tier for status in statuses.values()), key=rank.__getitem__)
    return {"domain_id": public_domain_id, "categories": [asdict(status) for status in statuses.values()],
            "overall_tier": overall.value}
