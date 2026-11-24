"""Core labeling routes backed by the async persistence repository."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from math import isfinite
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, null, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from db.connection import get_db
from db.models import Domain, LabelLog
from db import repository
from auth import Tenant, scoped_domain_id
from jm_core import ConservationState, DomainConfig, JudgmentMemoryEngine
from policy_engine import AutonomyTier, evaluate_domain
from rate_limit import limiter
from trial_guard import reserve_label_capacity

router = APIRouter(prefix="/v1/labels", tags=["Labeling"])
logger = logging.getLogger(__name__)
autonomy_router = APIRouter(prefix="/v1/domains", tags=["Labeling"])
Session = Annotated[AsyncSession, Depends(get_db)]


class GuidelinesPayload(BaseModel):
    guidelines: str | None = None

    @field_validator("guidelines")
    @classmethod
    def limit_guidelines(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-8")) > 10 * 1024:
            raise ValueError("Guidelines must be at most 10 KiB UTF-8")
        return value


async def guidelines_domain(domain_id: str, tenant: Tenant, session: Session) -> Domain:
    domain = await repository.get_domain(session, scoped_domain_id(tenant, domain_id))
    if domain is None:
        raise HTTPException(404, detail="Domain not found")
    return domain


@autonomy_router.get("/{domain_id}/guidelines", response_model=GuidelinesPayload)
async def get_guidelines(domain_id: str, tenant: Tenant, session: Session) -> GuidelinesPayload:
    domain = await guidelines_domain(domain_id, tenant, session)
    return GuidelinesPayload(guidelines=domain.guidelines)


@autonomy_router.put("/{domain_id}/guidelines", response_model=GuidelinesPayload)
async def put_guidelines(domain_id: str, payload: GuidelinesPayload, tenant: Tenant,
                         session: Session) -> GuidelinesPayload:
    domain = await guidelines_domain(domain_id, tenant, session)
    domain.guidelines = payload.guidelines
    return payload


class IngestItem(BaseModel):
    label_id: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=200)
    annotator_id: str | None = Field(default=None, max_length=200)
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
    domain_id: str = Field(min_length=1, max_length=200)


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
    domain_id: str = Field(min_length=1, max_length=200)
    label_id: str = Field(min_length=1, max_length=200)
    actual_action: str = Field(min_length=1)
    verified_outcome: bool
    annotator_id: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)


class VerifyResponse(BaseModel):
    label_id: str
    action_taken: str
    was_correct: bool
    engine_updated: bool
    new_accuracy: float | None


class BulkVerifyRequest(BaseModel):
    label_ids: list[str] = Field(min_length=1, max_length=200)
    action: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=1000)
    outcome: bool | None = None

    @field_validator("label_ids")
    @classmethod
    def valid_ids(cls, values: list[str]) -> list[str]:
        if (any(not value.strip() or len(value) > 200 or "|" in value for value in values)
                or len(set(values)) != len(values)):
            raise ValueError("label_ids must be unique, nonempty identifiers up to 200 characters")
        return values


class IngestBatchRequest(BaseModel):
    domain_id: str = Field(min_length=1, max_length=200)
    items: list[IngestItem] = Field(min_length=1, max_length=100)


class IngestBatchResponse(BaseModel):
    results: list[IngestResponse]
    batch_size: int


class TextTaskRequest(BaseModel):
    label_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    category: str | None = Field(default=None, max_length=200)

    @field_validator("text")
    @classmethod
    def bounded_text(cls, value: str) -> str:
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError("text must be valid UTF-8") from exc
        if size > 32 * 1024:
            raise ValueError("text must be at most 32 KiB UTF-8")
        return value

    @field_validator("label_id", "category")
    @classmethod
    def valid_name(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "|" in value):
            raise ValueError("Identifiers must be nonempty and cannot contain |")
        return value


class EditableNerSpan(BaseModel):
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, ge=1)
    label: str = Field(min_length=1, max_length=200)
    text: str | None = None

    @field_validator("label")
    @classmethod
    def valid_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Span label must be nonempty")
        return value


class RelabelRequest(BaseModel):
    category: str = Field(min_length=1, max_length=200)
    idempotency_token: str = Field(min_length=1, max_length=200)
    spans: list[EditableNerSpan] | None = Field(default=None, max_length=100)
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("category")
    @classmethod
    def valid_category(cls, value: str) -> str:
        if not value.strip() or "|" in value:
            raise ValueError("Invalid category")
        return value

    @field_validator("tags")
    @classmethod
    def valid_edit_tags(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        unique: list[str] = []
        seen: set[str] = set()
        for value in values:
            tag = value.strip()
            if not tag or len(tag) > 50:
                raise ValueError("Tags must be nonempty and at most 50 characters")
            key = tag.casefold()
            if key not in seen:
                unique.append(tag)
                seen.add(key)
        return unique


class NerSpan(BaseModel):
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, ge=0)
    label: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=32768)


class LabelContentRequest(BaseModel):
    content_type: Literal["text_ner", "text_multilabel", "image_classification"]
    spans: list[NerSpan] = Field(default_factory=list, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    image_url: str | None = Field(default=None, max_length=2048)

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 200 for value in values) or len(set(values)) != len(values):
            raise ValueError("Tags must be distinct, nonempty names up to 200 characters")
        return values

    @field_validator("image_url")
    @classmethod
    def valid_image_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or any(char.isspace() for char in value)):
            raise ValueError("image_url must be a bounded HTTPS URL without credentials or fragment")
        return value


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
    if row.scored_at is None:
        raise HTTPException(status_code=409, detail="Task needs a category before verification")
    if row.superseded_by is not None:
        raise HTTPException(status_code=409, detail="Label revision is stale")
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
    assert row.category is not None
    domain = await repository.get_domain(session, domain_id)
    categories = DomainConfig.from_dict(domain.config_json).categories if domain is not None else []
    if row.category not in categories:
        raise HTTPException(status_code=422, detail=f"Category not in domain schema: {row.category}")
    repository.sync_engine_categories(engine, categories)
    try:
        result = await repository.verify_and_learn(
            session, engine, domain_id, request.label_id,
            request.actual_action, request.verified_outcome, request.reason
        )
    except StaleDataError as exc:
        raise HTTPException(status_code=409, detail="Engine state changed; retry") from exc
    _, accuracy = await repository.verified_accuracy(session, domain_id, row.category)
    return VerifyResponse(label_id=request.label_id, action_taken=request.actual_action,
                          was_correct=request.verified_outcome,
                          engine_updated=result.centroid_moved, new_accuracy=accuracy)


@router.post("/{domain_id}/bulk-verify")
@limiter.limit("10/minute")
async def bulk_verify(request: Request, domain_id: str, payload: BulkVerifyRequest,
                      session: Session, tenant: Tenant) -> dict:
    scoped = scoped_domain_id(tenant, domain_id)
    domain = await repository.get_domain(session, scoped)
    if domain is None:
        raise HTTPException(404, detail="Domain not found")
    categories = set(DomainConfig.from_dict(domain.config_json).categories)
    rows = (await session.scalars(select(LabelLog).where(
        LabelLog.domain_id == scoped, LabelLog.tenant_id == tenant,
        LabelLog.label_id.in_(payload.label_ids)).with_for_update())).all()
    by_id = {row.label_id: row for row in rows}
    if len(by_id) != len(payload.label_ids):
        raise HTTPException(404, detail="One or more labels were not found in this domain")
    processed = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    capacity_error: str | None = None
    for label_id in payload.label_ids:
        row = by_id[label_id]
        if row.verified_at is not None:
            skipped += 1
            errors.append({"label_id": label_id, "error": "already_verified"})
            continue
        if row.scored_at is None or row.superseded_by is not None or row.recommended_action is None:
            skipped += 1
            errors.append({"label_id": label_id, "error": "not_pending_scored_label"})
            continue
        if row.category not in categories:
            raise HTTPException(422, detail=f"Category not in domain schema: {row.category}")
        if capacity_error is not None:
            skipped += 1
            errors.append({"label_id": label_id, "error": capacity_error})
            continue
        try:
            await reserve_label_capacity(session)
        except HTTPException as exc:
            if exc.status_code == 429 and isinstance(exc.detail, dict) and exc.detail.get("error") == "volume_exceeded":
                capacity_error = ("daily_cap_exceeded" if exc.detail.get("scope") == "daily"
                                  else "monthly_cap_exceeded")
                skipped += 1
                errors.append({"label_id": label_id, "error": capacity_error})
                continue
            raise
        actual_action = (row.recommended_action if payload.action == "approve" else
                         "reject" if row.recommended_action == "approve" else "approve")
        await verify(VerifyRequest(domain_id=domain_id, label_id=label_id,
                                   actual_action=actual_action,
                                   verified_outcome=(payload.action == "approve" if payload.outcome is None
                                                     else payload.outcome),
                                   reason=payload.reason), session, tenant)
        processed += 1
    return {"processed": processed, "skipped": skipped, "errors": errors}


@router.post("/ingest/batch", response_model=IngestBatchResponse)
async def ingest_batch(request: IngestBatchRequest, response: Response, session: Session,
                       tenant: Tenant) -> IngestBatchResponse:
    request_id = uuid4().hex
    results: list[IngestResponse] = []
    for index, item in enumerate(request.items):
        try:
            results.append(await _ingest(session, scoped_domain_id(tenant, request.domain_id), item,
                                         request.domain_id))
        except (HTTPException, SQLAlchemyError, StaleDataError, ValueError) as exc:
            if isinstance(exc, HTTPException) and exc.status_code in {402, 429}:
                raise
            if isinstance(exc, IntegrityError):
                logger.warning("Batch item %d conflict: %s", index, type(exc).__name__,
                               extra={"request_id": request_id})
                detail = f"Duplicate or conflict at item {index}"
            elif isinstance(exc, HTTPException):
                detail = exc.detail
            else:
                logger.warning("Batch item %d failed: %s", index, type(exc).__name__,
                               extra={"request_id": request_id})
                detail = f"Internal error processing item {index}"
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


@router.post("/{domain_id}/tasks", status_code=201)
async def create_text_task(domain_id: str, request: TextTaskRequest,
                           session: Session, tenant: Tenant) -> dict[str, str | None]:
    scoped = scoped_domain_id(tenant, domain_id)
    if await session.scalar(select(LabelLog.id).where(
            LabelLog.domain_id == scoped, LabelLog.tenant_id == tenant,
            LabelLog.label_id == request.label_id)) is not None:
        raise HTTPException(409, detail="Label already exists")
    if request.category is not None:
        domain = await repository.get_domain(session, scoped)
        config = DomainConfig.from_dict(domain.config_json) if domain else None
        factors = {name: 0.5 for name in (config.factors if config else
                   ["model_confidence", "item_difficulty"])}
        item = IngestItem(label_id=request.label_id, category=request.category,
                          factors=factors, text=request.text)
        try:
            await _ingest(session, scoped, item, domain_id)
        except (IntegrityError, StaleDataError) as exc:
            raise HTTPException(409, detail="Label already exists") from exc
        return {"label_id": request.label_id, "status": "scored", "category": request.category}
    domain = await repository.get_domain(session, scoped)
    if domain is None:
        config = DomainConfig(scoped, scoped, ["model_confidence", "item_difficulty"],
                              [], ["approve", "reject"])
        try:
            await repository.create_domain(session, scoped, scoped, config, public_domain_id=domain_id)
        except IntegrityError as exc:
            raise HTTPException(409, detail="Domain already exists") from exc
    elif domain.public_domain_id is None:
        domain.public_domain_id = domain_id
    session.add(LabelLog(domain_id=scoped, tenant_id=tenant, label_id=request.label_id,
                         category=None, factors_json={}, text=request.text,
                         recommended_action=None, confidence=None, scored_at=null()))
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(409, detail="Label already exists") from exc
    return {"label_id": request.label_id, "status": "pending_classification", "category": None}


@router.post("/{domain_id}/items/{label_id}/relabel")
async def relabel_item(domain_id: str, label_id: str, request: RelabelRequest,
                       session: Session, tenant: Tenant) -> dict[str, str | None]:
    scoped = scoped_domain_id(tenant, domain_id)
    original = await _current_label(session, domain_id, label_id, tenant, lock=True)
    if request.idempotency_token != str(original.id):
        raise HTTPException(409, detail="Stale label revision")
    if original.verified_at is not None and original.verified_outcome is True:
        raise HTTPException(409, detail="Cannot relabel a verified label. Use verify to change the outcome.")
    if original.scored_at is not None:
        domain = await repository.get_domain(session, scoped)
        if domain is None or request.category not in DomainConfig.from_dict(domain.config_json).categories:
            raise HTTPException(422, detail=f"Category not in domain schema: {request.category}")
    if request.spans is not None and request.tags is not None:
        raise HTTPException(422, detail="Edit spans or tags in one revision")
    edited_spans: list[dict] | None = None
    if request.spans is not None:
        if original.text is None:
            raise HTTPException(422, detail="Cannot edit spans without stored text")
        existing_content = await repository.get_label_content(session, original.id)
        if existing_content is not None and existing_content.content_type != "text_ner":
            raise HTTPException(422, detail="Only text NER content supports span edits")
        edited_spans = []
        previous_end = 0
        for span in sorted(request.spans, key=lambda value: (value.start, value.end)):
            if span.start < previous_end or span.start >= span.end or span.end > len(original.text):
                raise HTTPException(422, detail="Invalid or overlapping span offsets")
            mention = original.text[span.start:span.end]
            if span.text is not None and span.text != mention:
                raise HTTPException(422, detail="Span text does not match source")
            edited_spans.append({"start": span.start, "end": span.end,
                                 "label": span.label, "text": mention})
            previous_end = span.end
    if request.tags is not None:
        existing_content = await repository.get_label_content(session, original.id)
        if existing_content is not None and existing_content.content_type != "text_multilabel":
            raise HTTPException(422, detail="Only multilabel content supports tag edits")
    current_content = await repository.get_label_content(session, original.id)
    current_spans = current_content.spans_json if current_content is not None else []
    current_tags = current_content.tags_json if current_content is not None else []
    next_spans = edited_spans if edited_spans is not None else current_spans
    next_tags = request.tags if request.tags is not None else current_tags
    if request.category == original.category and next_spans == current_spans and next_tags == current_tags:
        raise HTTPException(409, detail="No change detected.")
    prior_category = original.category
    successor_label_id = f"revision:{uuid4().hex}"
    now = datetime.now(timezone.utc)
    if original.scored_at is None:
        domain = await repository.get_domain(session, scoped)
        assert domain is not None
        config = DomainConfig.from_dict(domain.config_json)
        factors = {name: 0.5 for name in config.factors}
        item = IngestItem(label_id=successor_label_id, category=request.category,
                          factors=factors, text=original.text)
        try:
            await _ingest(session, scoped, item, domain_id)
        except StaleDataError as exc:
            raise HTTPException(409, detail="Engine state changed; retry") from exc
        successor = await session.scalar(select(LabelLog).where(
            LabelLog.domain_id == scoped, LabelLog.tenant_id == tenant,
            LabelLog.label_id == successor_label_id))
        assert successor is not None
    else:
        successor = LabelLog(
            domain_id=scoped, tenant_id=tenant, label_id=successor_label_id,
            category=request.category, factors_json=original.factors_json,
            text=original.text, annotator_id=original.annotator_id,
            recommended_action=original.recommended_action, confidence=original.confidence,
            scored_at=original.scored_at,
            annotation_id=original.annotation_id)
        session.add(successor)
    successor.source_task_id = original.source_task_id or original.label_id
    successor.prior_revision_id = str(original.id)
    successor.revision_actor = tenant
    successor.revision_at = now
    successor.idempotency_token = request.idempotency_token
    original.superseded_by = successor_label_id
    await session.flush()
    if edited_spans is not None:
        await repository.record_label_content(session, successor.id, "text_ner", edited_spans, [], None)
    elif request.tags is not None:
        await repository.record_label_content(session, successor.id, "text_multilabel", [], request.tags, None)
    else:
        await repository.copy_label_content(session, original.id, successor.id)
    return {"label_id": label_id, "category": request.category,
            "revision_id": str(successor.id), "previous_category": prior_category}


@router.get("/{domain_id}/pending")
@limiter.limit("60/minute")
async def pending(request: Request, domain_id: str, response: Response, session: Session, tenant: Tenant,
                  category: str | None = None, limit: int = Query(default=50, ge=1, le=200),
                  offset: int = Query(default=0, ge=0),
                  sort_by: Literal["label_id", "category", "annotator_id", "confidence", "recommended_action"] | None = None,
                  sort_order: Literal["asc", "desc"] = "asc",
                  search: str | None = Query(default=None, max_length=200)) -> list[dict]:
    domain_id = scoped_domain_id(tenant, domain_id)
    if await repository.get_domain(session, domain_id) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    filters = [LabelLog.domain_id == domain_id, LabelLog.tenant_id == tenant,
               LabelLog.verified_at.is_(None), LabelLog.scored_at.is_not(None),
               LabelLog.superseded_by.is_(None)]
    if category is not None:
        filters.append(LabelLog.category == category)
    search_lower = search.strip().lower() if search is not None else ""
    if search_lower:
        filters.append(or_(
            func.lower(LabelLog.label_id).contains(search_lower, autoescape=True),
            func.lower(LabelLog.annotator_id).contains(search_lower, autoescape=True),
            func.lower(LabelLog.category).contains(search_lower, autoescape=True),
            func.lower(LabelLog.text).contains(search_lower, autoescape=True),
        ))
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


async def _current_label(session: AsyncSession, domain_id: str, label_id: str,
                         tenant: str, *, lock: bool = False) -> LabelLog:
    scoped = scoped_domain_id(tenant, domain_id)
    query = select(LabelLog).where(LabelLog.domain_id == scoped,
                                   LabelLog.tenant_id == tenant, LabelLog.label_id == label_id)
    row = await session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, detail="Label not found")
    while row.superseded_by is not None:
        query = select(LabelLog).where(LabelLog.domain_id == scoped,
                                       LabelLog.tenant_id == tenant,
                                       LabelLog.label_id == row.superseded_by)
        successor = await session.scalar(query.with_for_update() if lock else query)
        if successor is None:
            raise HTTPException(409, detail="Label revision chain is incomplete")
        row = successor
    return row


@router.post("/{domain_id}/items/{label_id}/content", status_code=201)
async def create_label_content(domain_id: str, label_id: str, payload: LabelContentRequest,
                               session: Session, tenant: Tenant) -> dict[str, str | int]:
    row = await _current_label(session, domain_id, label_id, tenant, lock=True)
    if await repository.get_label_content(session, row.id) is not None:
        raise HTTPException(409, detail="Content already exists for this revision")
    domain = await repository.get_domain(session, scoped_domain_id(tenant, domain_id))
    assert domain is not None
    categories = set(DomainConfig.from_dict(domain.config_json).categories)
    if payload.content_type == "text_ner":
        if row.text is None:
            raise HTTPException(422, detail="Source text is required for NER spans")
        if payload.tags or payload.image_url is not None:
            raise HTTPException(422, detail="NER content accepts spans only")
    elif payload.content_type == "text_multilabel":
        if payload.spans or payload.image_url is not None:
            raise HTTPException(422, detail="Multilabel content accepts tags only")
    elif payload.spans or payload.image_url is None:
        raise HTTPException(422, detail="Image classification requires an HTTPS image URL and no spans")
    if any(tag not in categories for tag in payload.tags):
        raise HTTPException(422, detail="Unknown tag label")
    spans = sorted(payload.spans, key=lambda span: (span.start, span.end))
    previous_end = 0
    for span in spans:
        if span.label not in categories:
            raise HTTPException(422, detail="Unknown span label")
        if (row.text is None or span.start >= span.end or span.end > len(row.text)
                or span.start < previous_end):
            raise HTTPException(422, detail="Invalid or overlapping span offsets")
        if row.text[span.start:span.end] != span.text:
            raise HTTPException(422, detail="Span text does not match source")
        previous_end = span.end
    try:
        await repository.record_label_content(session, row.id, payload.content_type,
                                              [span.model_dump() for span in spans],
                                              payload.tags, payload.image_url)
    except IntegrityError as exc:
        raise HTTPException(409, detail="Content already exists for this revision") from exc
    count_key = "spans_count" if payload.content_type == "text_ner" else "tags_count"
    return {"label_id": row.label_id, "content_type": payload.content_type,
            count_key: len(spans) if count_key == "spans_count" else len(payload.tags)}


@router.get("/{domain_id}/items/{label_id}")
@router.get("/{domain_id}/{label_id}")
@limiter.limit("60/minute")
async def label_detail(request: Request, domain_id: str, label_id: str,
                       session: Session, tenant: Tenant) -> dict:
    row = await _current_label(session, domain_id, label_id, tenant)
    previous_category = None
    if row.prior_revision_id is not None:
        prior = await session.scalar(select(LabelLog).where(
            LabelLog.domain_id == scoped_domain_id(tenant, domain_id),
            LabelLog.tenant_id == tenant, LabelLog.id == UUID(row.prior_revision_id)))
        previous_category = prior.category if prior and prior.category != row.category else None
    content = await repository.get_label_content(session, row.id)
    return {"domain_id": domain_id, "label_id": row.label_id, "category": row.category,
            "annotator_id": row.annotator_id, "factors": row.factors_json,
            "recommended_action": row.recommended_action, "confidence": row.confidence,
            "text": row.text, "actual_action": row.actual_action,
            "verified_outcome": row.verified_outcome,
            "verified_at": row.verified_at.isoformat() if row.verified_at else None,
            "revision_id": str(row.id), "previous_category": previous_category,
            "status": "pending_classification" if row.scored_at is None else "scored",
            "content": None if content is None else {
                "content_type": content.content_type, "spans": content.spans_json,
                "tags": content.tags_json, "image_url": content.image_url}}


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
    overall = min((status.tier for status in statuses.values()), key=rank.__getitem__,
                  default=AutonomyTier.RED)
    return {"domain_id": public_domain_id, "categories": [asdict(status) for status in statuses.values()],
            "overall_tier": overall.value}
