"""Core labeling routes backed by the async persistence repository."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import asyncio
import tempfile
from collections.abc import AsyncIterator
from starlette.types import Scope, Receive, Send
import csv
import hashlib
import heapq
import io
import json
import logging

from math import isfinite
from pathlib import Path
from time import monotonic
from typing import Annotated, Any, ClassVar, Literal, Self, Sequence
from sqlalchemy.orm import defer
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ModelWrapValidatorHandler, PrivateAttr, field_validator, model_validator
from sqlalchemy import String, bindparam, case, func, null, or_, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from modality import (MAX_INLINE, media_caption, validate_data_uri, validate_image_url,
                      validate_layout, validate_media_for_project)
from db.connection import commit_write, get_db
from db import connection
from db.models import (Annotator, ApiKey, Domain, Engine, LabelContent, LabelLog, Prediction,
                       ProjectExportSlot, ProjectMember, ProjectRequest)
from db.entitlement import effective_state
from db.tenant_lock import lock_tenant
from db import repository
from auth import ProjectTenant, selected_domain_id
from jm_core import ConservationState, DomainConfig, JudgmentMemoryEngine
from policy_engine import AutonomyTier, evaluate_domain
from rate_limit import limiter
from trial_guard import reserve_label_capacity

router = APIRouter(prefix="/v1/labels", tags=["Labeling"])
project_labels_router = APIRouter(prefix="/v1/projects/{domain_id}/labels", tags=["Project labels"])
project_meta_router = APIRouter(prefix="/v1/projects/{domain_id}", tags=["Project review"])
logger = logging.getLogger(__name__)
autonomy_router = APIRouter(prefix="/v1/domains", tags=["Labeling"])
Session = Annotated[AsyncSession, Depends(get_db)]


async def require_active_project(session: AsyncSession, domain: Domain) -> None:
    await session.refresh(domain, with_for_update=True)
    if domain.status != "active":
        raise HTTPException(409, detail="Project is read-only")


class GuidelinesPayload(BaseModel):
    guidelines: str | None = None
    guidelines_updated_at: datetime | None = None

    @field_validator("guidelines")
    @classmethod
    def limit_guidelines(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-8")) > 10 * 1024:
            raise ValueError("Guidelines must be at most 10 KiB UTF-8")
        return value


async def guidelines_domain(domain_id: str, tenant: ProjectTenant, session: Session) -> Domain:
    domain = await repository.get_domain(session, selected_domain_id(session, tenant, domain_id))
    if domain is None:
        raise HTTPException(404, detail="Domain not found")
    return domain


@autonomy_router.get("/{domain_id}/guidelines", response_model=GuidelinesPayload)
async def get_guidelines(domain_id: str, tenant: ProjectTenant, session: Session) -> GuidelinesPayload:
    domain = await guidelines_domain(domain_id, tenant, session)
    return GuidelinesPayload(guidelines=domain.guidelines,
                             guidelines_updated_at=domain.guidelines_updated_at)


@autonomy_router.put("/{domain_id}/guidelines", response_model=GuidelinesPayload)
async def put_guidelines(domain_id: str, payload: GuidelinesPayload, tenant: ProjectTenant,
                         session: Session) -> GuidelinesPayload:
    domain = await guidelines_domain(domain_id, tenant, session)
    await require_active_project(session, domain)
    domain.guidelines = payload.guidelines
    domain.guidelines_updated_at = datetime.now(timezone.utc)
    await commit_write(session)
    return GuidelinesPayload(guidelines=domain.guidelines,
                             guidelines_updated_at=domain.guidelines_updated_at)


class NerSpan(BaseModel):
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, ge=0)
    label: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=32768)


class LabelContentRequest(BaseModel):
    content_type: Literal["text_ner", "text_multilabel", "image_classification"]
    spans: list[NerSpan] = Field(default_factory=list, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    image_url: str | None = Field(default=None, description="HTTPS URL (2048 characters) or a base64 JPEG, PNG, GIF or WebP (10 MiB decoded).")

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
        if value[:5].lower() == "data:":
            return validate_data_uri(value)[0]
        return validate_image_url(value, strict=False)

    @property
    def decoded_size(self) -> int:
        value = self.image_url
        if not value or not value.startswith("data:"):
            return 0
        length = len(value) - value.index(",") - 1
        return length // 4 * 3 - int(value.endswith("=")) - int(value.endswith("=="))


class MediaInput(BaseModel):
    """Flat item_text/item_media_url and nested fields share one receipt representation."""
    content: LabelContentRequest | None = None
    _has_flat_annotations: bool = PrivateAttr(default=False)

    @model_validator(mode="wrap")
    @classmethod
    def remember_flat_annotations(cls, value: Any, handler: ModelWrapValidatorHandler[Self]) -> Self:
        item = handler(value)
        if isinstance(value, dict):
            # Old clients could send ignored extra fields. Preserve receipt bytes while
            # retaining enough information for strict projects to refuse lossy input.
            item._has_flat_annotations = bool(value.get("tags") or value.get("spans"))
        return item

    def check_annotation_fields(self, project: Domain | None, index: int | None = None) -> None:
        if self._has_flat_annotations and project is not None and project.modality_enforced:
            prefix = "" if index is None else f"Item {index}: "
            raise HTTPException(422, prefix + "Content does not match project modality")

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if (value.get("tags") or value.get("spans")) and (
                value.get("item_media_url") is not None or
                isinstance(value.get("content"), dict) and value["content"].get("image_url") is not None):
            raise HTTPException(422, "Content does not match project modality")
        if not ({"item_text", "item_media_url"} & value.keys()):
            return value
        result = value.copy()
        conflict = HTTPException(422, "Conflicting values for text or image URL")
        if "item_text" in result:
            caption = result.pop("item_text")
            if "text" in result and result["text"] != caption:
                raise conflict
            result["text"] = caption
        if "item_media_url" in result:
            media = result.pop("item_media_url")
            nested = result.get("content")
            if isinstance(nested, dict) and "image_url" in nested and nested["image_url"] != media:
                raise conflict
            if media is not None:
                if nested is not None and (not isinstance(nested, dict) or
                        nested.get("content_type", "image_classification") != "image_classification"):
                    raise conflict
                result["content"] = {**(nested or {}), "content_type": "image_classification",
                                     "image_url": media}
        return result

    @classmethod
    def __get_pydantic_json_schema__(cls, schema, handler):
        result = handler.resolve_ref_schema(handler(schema))
        result["properties"].update({
            "item_text": {"type": ["string", "null"], "description": "Input alias for text."},
            "item_media_url": {"type": ["string", "null"], "description": "Input alias for content.image_url."},
        })
        return result


class IngestItem(MediaInput):
    label_id: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=200)
    annotator_id: str | None = Field(default=None, max_length=200)
    factors: dict[str, float] = Field(min_length=2, max_length=20)
    text: str | None = None
    notes: str | None = Field(default=None, max_length=500)

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
        if any(not name.strip() or len(name) > 200 or not isfinite(value) or not 0 <= value <= 1
               for name, value in factors.items()):
            raise ValueError("Factor names must be 1 to 200 characters and values finite in [0, 1]")
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
    actual_action: str = Field(min_length=1, max_length=200)
    verified_outcome: bool
    annotator_id: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=500)


class VerifyResponse(BaseModel):
    label_id: str
    action_taken: str
    was_correct: bool
    engine_updated: bool
    new_accuracy: float | None


class BulkVerifyItem(BaseModel):
    label_id: str = Field(min_length=1, max_length=200)
    verified_outcome: bool | None = Field(default=None, strict=True)


class BulkVerifyRequest(BaseModel):
    label_ids: list[str] = Field(default_factory=list, max_length=200)
    items: list[BulkVerifyItem] | None = Field(default=None, max_length=200)
    action: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=1000)
    outcome: bool | None = Field(default=None, strict=True)

    @field_validator("label_ids")
    @classmethod
    def valid_ids(cls, values: list[str]) -> list[str]:
        if (any(not value.strip() or len(value) > 200 or "|" in value for value in values)
                or len(set(values)) != len(values)):
            raise ValueError("label_ids must be unique, nonempty identifiers up to 200 characters")
        return values

    @model_validator(mode="after")
    def valid_selection(self) -> BulkVerifyRequest:
        if bool(self.label_ids) == bool(self.items):
            raise ValueError("Provide label_ids or items")
        if self.items and len({item.label_id for item in self.items}) != len(self.items):
            raise ValueError("Item IDs must be unique")
        return self


def validate_batch_media(items: Sequence[MediaInput]) -> None:
    if sum(item.content.decoded_size for item in items if item.content) > MAX_INLINE:
        raise HTTPException(413, "Embedded images exceed 10 MiB")


class MediaBatch(BaseModel):
    item_model: ClassVar[type[MediaInput]]

    @field_validator("items", mode="before", check_fields=False)
    @classmethod
    def indexed_items(cls, values: Any) -> Any:
        if not isinstance(values, list) or not 1 <= len(values) <= 100:
            return values
        items = []
        for index, value in enumerate(values):
            try:
                items.append(cls.item_model.model_validate(value))
            except HTTPException as exc:
                if exc.status_code != 422:
                    raise
                raise HTTPException(422, f"Item {index}: {exc.detail}") from None
        validate_batch_media(items)
        return items


class IngestBatchRequest(MediaBatch):
    item_model = IngestItem
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


class RevisionRequest(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def immutable_source(cls, value: Any) -> Any:
        if isinstance(value, dict) and {"item_media_url", "image_url", "content"} & value.keys():
            raise HTTPException(422, "This operation does not support the project modality")
        return value


class RelabelRequest(RevisionRequest):
    category: str = Field(min_length=1, max_length=200)
    idempotency_token: str = Field(min_length=1, max_length=200)
    spans: list[EditableNerSpan] | None = Field(default=None, max_length=100)
    tags: list[str] | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=500)

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


class ProjectImportItem(IngestItem):
    """Project-scoped typed label import."""


class ProjectImportBatch(MediaBatch):
    item_model = ProjectImportItem
    request_key: str = Field(min_length=1, max_length=200)
    items: list[ProjectImportItem] = Field(min_length=1, max_length=100)


class ProjectVerifyInput(BaseModel):
    label_id: str = Field(min_length=1, max_length=200)
    actual_action: str = Field(min_length=1, max_length=200)
    verified_outcome: bool
    annotator_id: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=500)


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


_stats_domain = bindparam("stats_domain", type_=String())
_stats_tenant = bindparam("stats_tenant", type_=String())
_category_observations = (
    select(LabelLog.category, LabelLog.verified_outcome)
    .where(LabelLog.domain_id == _stats_domain, LabelLog.tenant_id == _stats_tenant,
           repository.active_verified_evidence(_stats_domain, _stats_tenant),
           LabelLog.verified_at.is_not(None), LabelLog.verified_outcome.is_not(None))
    .order_by(LabelLog.verified_at, LabelLog.scored_at, LabelLog.id).execution_options(yield_per=500)
)


async def _category_stats(session: AsyncSession, domain_id: str,
                          categories: list[str]) -> dict[str, dict]:
    rows = await session.stream(_category_observations, {
        "stats_domain": domain_id, "stats_tenant": session.info.get("tenant_id", "")})
    gates = {category: ConservationState() for category in categories}
    correct_totals = dict.fromkeys(categories, 0)
    async for category, outcome in rows:
        if category in gates:
            gates[category].update(bool(outcome), category)
            correct_totals[category] += int(bool(outcome))
    stats: dict[str, dict] = {}
    for category, gate in gates.items():
        recent = gate.accuracy_window[-50:]
        passed, reason = gate.check_gate(1)
        stats[category] = {
            "verified_count": gate.total_verified,
            "accuracy": correct_totals[category] / gate.total_verified if gate.total_verified else None,
            "rolling_accuracy": sum(recent) / len(recent) if recent else None,
            "conservation_gate_pass": passed,
            "conservation_reason": reason if reason != "clear" else None,
        }
    return stats


def prepare_content(domain: Domain | None, item: IngestItem | PredictionItem,
                    known: set[str], index: int | None = None) -> None:
    item.check_annotation_fields(domain, index)
    content = item.content
    try:
        validate_media_for_project(domain, content.content_type if content else None,
                                   content.image_url if content else None,
                                   spans=bool(content and content.spans), tags=bool(content and content.tags))
        if domain is not None and domain.modality_enforced and domain.label_schema != "single":
            if item.category not in domain.config_json["categories"]:
                raise HTTPException(422, "Category not in domain schema")
        if content is None:
            return
        if content.content_type == "text_ner":
            if item.text is None or content.tags or content.image_url:
                raise HTTPException(422, "Invalid NER content")
            previous_end = 0
            for span in sorted(content.spans, key=lambda value: (value.start, value.end)):
                if (span.label not in known or span.start < previous_end or span.start >= span.end
                        or span.end > len(item.text) or item.text[span.start:span.end] != span.text):
                    raise HTTPException(422, "Invalid NER span")
                previous_end = span.end
        elif content.content_type == "text_multilabel":
            if content.spans or content.image_url or set(content.tags) - known:
                raise HTTPException(422, "Invalid tags")
        elif not content.image_url or content.tags or content.spans:
            raise HTTPException(422, "Content does not match project modality")
        elif not item.text and domain is not None and domain.modality_enforced:
            item.text = media_caption(content.image_url)
    except HTTPException as exc:
        if index is None:
            raise
        raise HTTPException(exc.status_code, f"Item {index}: {exc.detail}") from None


async def _prepare_engine(session: AsyncSession, domain_id: str,
                          item: IngestItem, public_domain_id: str | None = None,
                          locked_domain: Domain | None = None) -> JudgmentMemoryEngine:
    domain = locked_domain
    if domain is None:
        domain = await repository.get_domain(session, domain_id)
        if domain is not None:
            await require_active_project(session, domain)
    known = set(domain.config_json["categories"]) if domain is not None else set()
    prepare_content(domain, item, known | {item.category})
    if domain is None:
        config = DomainConfig(domain_id, domain_id, list(item.factors), [item.category],
                              ["approve", "reject"])
        await repository.create_domain(session, domain_id, domain_id, config,
                                       public_domain_id=public_domain_id)
    else:
        if domain.public_domain_id is None and public_domain_id is not None and not session.info.get("selected_project_id"):
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
                  public_domain_id: str | None = None, *, locked_domain: Domain | None = None,
                  locked_payer: ApiKey | None = None,
                  evidence_cache: dict[tuple[str, ...], dict[str, dict]] | None = None) -> IngestResponse:
    engine = await _prepare_engine(session, domain_id, item, public_domain_id, locked_domain)
    await reserve_label_capacity(session, locked_payer)
    result = await repository.score_and_persist(
        session, engine, domain_id, item.label_id, item.annotator_id,
        item.category, item.factors, item.text, item.notes
    )
    if item.content is not None:
        row_id = await session.scalar(select(LabelLog.id).where(LabelLog.domain_id == domain_id,
                                      LabelLog.tenant_id == session.info["tenant_id"],
                                      LabelLog.label_id == item.label_id))
        assert row_id is not None
        await repository.record_label_content(session, row_id, item.content.content_type,
                                              [span.model_dump() for span in item.content.spans],
                                              item.content.tags, item.content.image_url)
    if item.annotator_id is not None:
        await repository.upsert_annotator(session, domain_id, item.annotator_id)
    vocabulary = tuple(engine.config.categories)
    stats = evidence_cache.get(vocabulary) if evidence_cache is not None else None
    if stats is None:
        stats = await _category_stats(session, domain_id, engine.config.categories)
        if evidence_cache is not None:
            evidence_cache[vocabulary] = stats
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


def request_digest(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def matches_import_receipt(stored: str, current: str, payload: ProjectImportBatch) -> bool:
    # MM-01 used exactly the current canonical DTO, including null content and notes.
    if stored == current:
        return True
    # Before notes existed, only this one absent default differed. Never discard media.
    if any(item.notes is not None or (item.content and item.content.decoded_size) for item in payload.items):
        return False
    old = payload.model_dump(mode="json", exclude={"items": {"__all__": {"notes"}}})
    return stored == request_digest(old)


@project_labels_router.post("/batch")
async def project_import_batch(request: Request, domain_id: str, payload: ProjectImportBatch,
                               session: Session, tenant: ProjectTenant) -> dict:
    """Atomic typed import with a durable, actor-scoped replay receipt."""
    scoped = selected_domain_id(session, tenant, domain_id)
    locked = getattr(request.state, "locked_project_write", None)
    transaction = session.sync_session.get_transaction()
    payer: ApiKey | None = None
    if locked is not None and transaction is not None and locked[0] is transaction:
        domain, payer = locked[1:]
        if domain.tenant_id != tenant or domain.domain_id != scoped:
            raise HTTPException(404, detail="Project not found")
    else:
        domain = await repository.get_domain(session, scoped)
        if domain is None:
            raise HTTPException(404, detail="Project not found")
        await require_active_project(session, domain)
    actor = session.info.get("actor_key_id")
    if actor is None:
        raise HTTPException(401, detail="Authenticated actor is unavailable")
    digest = request_digest(payload.model_dump(mode="json"))
    receipt = await session.get(ProjectRequest, (domain.id, actor, "import_batch", payload.request_key),
                                with_for_update=True)
    if receipt is not None:
        for index, item in enumerate(payload.items):
            item.check_annotation_fields(domain, None if session.info.get("single_import") else index)
        if not matches_import_receipt(receipt.payload_digest, digest, payload):
            raise HTTPException(409, detail="Request key was used with different content")
        return dict(receipt.result_json)
    if len({item.label_id for item in payload.items}) != len(payload.items):
        raise HTTPException(422, detail="Duplicate label ID in batch")
    known = set(domain.config_json["categories"])
    for index, item in enumerate(payload.items):
        known.add(item.category)
        prepare_content(domain, item, known, None if session.info.get("single_import") else index)
        if set(item.factors) != set(domain.config_json["factors"]):
            raise HTTPException(422, "Factor names differ from the domain schema")
    results: list[dict] = []
    # This transaction holds the project lock and only inserts unverified scores.
    evidence_cache: dict[tuple[str, ...], dict[str, dict]] = {}
    for index, item in enumerate(payload.items):
        try:
            outcome = await _ingest(session, scoped, item, domain_id, locked_domain=domain,
                                    locked_payer=payer, evidence_cache=evidence_cache)
            results.append(outcome.model_dump(mode="json"))
        except (IntegrityError, StaleDataError) as exc:
            raise HTTPException(409, detail=f"Import conflict at item {index}") from exc
    result = {"results": results, "batch_size": len(results)}
    session.add(ProjectRequest(project_id=domain.id, actor_key_id=actor,
                               operation="import_batch", request_key=payload.request_key,
                               payload_digest=digest, result_json=result,
                               expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
    await commit_write(session)
    return result


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest, response: Response, session: Session, tenant: ProjectTenant) -> IngestResponse:
    try:
        result = await _ingest(session, selected_domain_id(session, tenant, request.domain_id), request,
                               session.info.get("selected_project_public_id", request.domain_id))
        if warning := session.info.get("volume_warning"):
            response.headers["X-Volume-Warning"] = warning
        await commit_write(session)
        return result
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Domain or label already exists") from exc
    except StaleDataError as exc:
        raise HTTPException(status_code=409, detail="Engine state changed; retry") from exc
@router.post("/verify", response_model=VerifyResponse)
async def verify(request: VerifyRequest, session: Session, tenant: ProjectTenant) -> VerifyResponse:
    domain_id = selected_domain_id(session, tenant, request.domain_id)
    domain = await repository.get_domain(session, domain_id)
    if domain is None:
        raise HTTPException(404, detail="Domain not found")
    await require_active_project(session, domain)
    result_row = (await session.execute(select(
        LabelLog, LabelContent.content_type, LabelContent.image_url.is_not(None)
    ).outerjoin(LabelContent, LabelContent.label_log_id == LabelLog.id).where(
        LabelLog.domain_id == domain_id, LabelLog.tenant_id == tenant,
        LabelLog.label_id == request.label_id).with_for_update(of=LabelLog))).one_or_none()
    if result_row is None:
        raise HTTPException(status_code=404, detail="Label not found")
    row, kind, has_image = result_row
    validate_layout(domain, kind, has_image)
    prediction = await repository.prediction_for_revision(session, row.id)
    if prediction is not None and prediction.state == "human_reviewed":
        raise HTTPException(409, detail="Prediction is already reviewed")
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
    categories = DomainConfig.from_dict(domain.config_json).categories
    if row.category not in categories:
        raise HTTPException(status_code=422, detail="Category not in domain schema")
    repository.sync_engine_categories(engine, categories)
    try:
        result = await repository.verify_and_learn(
            session, engine, domain_id, request.label_id,
            request.actual_action, request.verified_outcome, request.reason, request.notes
        )
    except StaleDataError as exc:
        raise HTTPException(status_code=409, detail="Engine state changed; retry") from exc
    await repository.record_webhook_event(session, domain, "label.verified", str(row.id), {
        "label_id": row.label_id,
        "revision_id": str(row.id),
        "actual_action": request.actual_action,
        "verified_outcome": request.verified_outcome,
    })
    if prediction is not None:
        repository.record_unassessed_prediction_review(prediction, row)
    _, accuracy = await repository.verified_accuracy(session, domain_id, row.category)
    if not session.info.get("bulk_verify_active"):
        await commit_write(session)
    return VerifyResponse(label_id=request.label_id, action_taken=request.actual_action,
                          was_correct=request.verified_outcome,
                          engine_updated=result.centroid_moved, new_accuracy=accuracy)


@router.post("/{domain_id}/bulk-verify")
@limiter.limit("10/minute")
async def bulk_verify(request: Request, domain_id: str, payload: BulkVerifyRequest,
                      session: Session, tenant: ProjectTenant) -> dict:
    requested = (payload.items if payload.items is not None else
                 [BulkVerifyItem(label_id=label_id, verified_outcome=payload.outcome)
                  for label_id in payload.label_ids])
    requested_ids = [item.label_id for item in requested]
    scoped = selected_domain_id(session, tenant, domain_id)
    domain = await repository.get_domain(session, scoped)
    if domain is None:
        raise HTTPException(404, detail="Domain not found")
    await require_active_project(session, domain)
    categories = set(DomainConfig.from_dict(domain.config_json).categories)
    rows = (await session.scalars(select(LabelLog).where(
        LabelLog.domain_id == scoped, LabelLog.tenant_id == tenant,
        LabelLog.label_id.in_(requested_ids)).order_by(LabelLog.id).with_for_update())).all()
    by_id = {row.label_id: row for row in rows}
    if len(by_id) != len(requested_ids):
        raise HTTPException(404, detail="One or more labels were not found in this domain")
    processed = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    capacity_error: str | None = None
    session.info["bulk_verify_active"] = True
    for item in requested:
        label_id = item.label_id
        row = by_id[label_id]
        if item.verified_outcome is None:
            skipped += 1
            errors.append({"label_id": label_id, "error": "outcome_required"})
            continue
        if row.verified_at is not None:
            skipped += 1
            errors.append({"label_id": label_id, "error": "already_verified"})
            continue
        if row.scored_at is None or row.superseded_by is not None or row.recommended_action is None:
            skipped += 1
            errors.append({"label_id": label_id, "error": "not_pending_scored_label"})
            continue
        if row.category not in categories:
            raise HTTPException(422, detail="Category not in domain schema")
        prediction = await repository.prediction_for_revision(session, row.id)
        if prediction is not None and prediction.state != "pending":
            skipped += 1
            errors.append({"label_id": label_id, "error": "prediction_review_required"})
            continue
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
                                   verified_outcome=item.verified_outcome,
                                   reason=payload.reason), session, tenant)
        processed += 1
    session.info.pop("bulk_verify_active", None)
    await commit_write(session)
    return {"processed": processed, "skipped": skipped, "errors": errors}


@router.post("/ingest/batch", response_model=IngestBatchResponse)
async def ingest_batch(request: IngestBatchRequest, response: Response, session: Session,
                       tenant: ProjectTenant) -> IngestBatchResponse:
    scoped = selected_domain_id(session, tenant, request.domain_id)
    domain = await repository.get_domain(session, scoped)
    known = set(domain.config_json["categories"]) if domain else set()
    for index, item in enumerate(request.items):
        known.add(item.category)
        prepare_content(domain, item, known, index)
    request_id = uuid4().hex
    results: list[IngestResponse] = []
    for index, item in enumerate(request.items):
        try:
            results.append(await _ingest(session, selected_domain_id(session, tenant, request.domain_id), item,
                                         session.info.get("selected_project_public_id", request.domain_id)))
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
    await commit_write(session)
    return IngestBatchResponse(results=results, batch_size=len(results))


@router.post("/{domain_id}/sample")
async def seed_sample(domain_id: str, response: Response, session: Session, tenant: ProjectTenant) -> dict[str, str | int]:
    if session.info.get("selected_project_public_id", domain_id) != SAMPLE_DOMAIN:
        raise HTTPException(404, detail="Sample domain not found")
    items = _sample_items()
    scoped = selected_domain_id(session, tenant, domain_id)
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:scope))"), {"scope": scoped})
    domain = await repository.get_domain(session, scoped)
    validate_media_for_project(domain, None, None)
    if domain is not None and domain.domain_name != SAMPLE_MARKER:
        raise HTTPException(409, detail="Domain name is already in use")
    if domain is not None:
        await require_active_project(session, domain)
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
    await commit_write(session)
    return {"domain_id": domain_id, "created": created,
            "existing": len(existing_ids), "pending": len(pending_ids)}


@router.post("/{domain_id}/tasks", status_code=201)
async def create_text_task(domain_id: str, request: TextTaskRequest,
                           session: Session, tenant: ProjectTenant) -> dict[str, str | None]:
    if not 0 < len(domain_id) <= 200:
        raise HTTPException(422, detail="domain_id must be 1 to 200 characters")
    scoped = selected_domain_id(session, tenant, domain_id)
    domain = await repository.get_domain(session, scoped)
    validate_media_for_project(domain, None, None)
    if await session.scalar(select(LabelLog.id).where(
            LabelLog.domain_id == scoped, LabelLog.tenant_id == tenant,
            LabelLog.label_id == request.label_id)) is not None:
        raise HTTPException(409, detail="Label already exists")
    if request.category is not None:
        domain = await repository.get_domain(session, scoped)
        if domain is not None:
            await require_active_project(session, domain)
        config = DomainConfig.from_dict(domain.config_json) if domain else None
        factors = {name: 0.5 for name in (config.factors if config else
                   ["model_confidence", "item_difficulty"])}
        item = IngestItem(label_id=request.label_id, category=request.category,
                          factors=factors, text=request.text)
        try:
            await _ingest(session, scoped, item, domain_id)
        except (IntegrityError, StaleDataError) as exc:
            raise HTTPException(409, detail="Label already exists") from exc
        await commit_write(session)
        return {"label_id": request.label_id, "status": "scored", "category": request.category}
    domain = await repository.get_domain(session, scoped)
    if domain is None:
        config = DomainConfig(scoped, scoped, ["model_confidence", "item_difficulty"],
                              [], ["approve", "reject"])
        try:
            await repository.create_domain(session, scoped, scoped, config, public_domain_id=domain_id)
        except IntegrityError as exc:
            raise HTTPException(409, detail="Domain already exists") from exc
    elif domain.public_domain_id is None and session.info.get("selected_project_id") != domain_id:
        domain.public_domain_id = domain_id
    if domain is not None:
        await require_active_project(session, domain)
    session.add(LabelLog(domain_id=scoped, tenant_id=tenant, label_id=request.label_id,
                         category=None, factors_json={}, text=request.text,
                         recommended_action=None, confidence=None, scored_at=null()))
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(409, detail="Label already exists") from exc
    await commit_write(session)
    return {"label_id": request.label_id, "status": "pending_classification", "category": None}


@router.post("/{domain_id}/items/{label_id}/relabel")
async def relabel_item(domain_id: str, label_id: str, request: RelabelRequest,
                       session: Session, tenant: ProjectTenant) -> dict[str, str | None]:
    scoped = selected_domain_id(session, tenant, domain_id)
    project = await repository.get_domain(session, scoped)
    if project is not None:
        await require_active_project(session, project)
    original = await _current_label(session, domain_id, label_id, tenant, lock=True)
    if request.idempotency_token != str(original.id):
        raise HTTPException(409, detail="Stale label revision")
    if original.verified_at is not None and original.verified_outcome is True:
        raise HTTPException(409, detail="Cannot relabel a verified label. Use verify to change the outcome.")
    if original.scored_at is not None:
        domain = await repository.get_domain(session, scoped)
        if domain is None or request.category not in DomainConfig.from_dict(domain.config_json).categories:
            raise HTTPException(422, detail="Category not in domain schema")
    if project is not None and project.modality_enforced:
        if ((request.spans is not None and project.label_schema != "ner") or
                (request.tags is not None and project.label_schema != "multi")):
            raise HTTPException(422, "Content does not match project modality")
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
    validate_layout(project, current_content.content_type if current_content else None,
                    bool(current_content and current_content.image_url))
    current_spans = current_content.spans_json if current_content is not None else []
    current_tags = current_content.tags_json if current_content is not None else []
    next_spans = edited_spans if edited_spans is not None else current_spans
    next_tags = request.tags if request.tags is not None else current_tags
    content_type_changed = ((request.spans is not None and
                             (current_content is None or current_content.content_type != "text_ner")) or
                            (request.tags is not None and
                             (current_content is None or current_content.content_type != "text_multilabel")))
    notes_changed = request.notes is not None and request.notes != original.review_notes
    if (not content_type_changed and request.category == original.category and next_spans == current_spans
            and set(next_tags) == set(current_tags) and not notes_changed):
        raise HTTPException(409, detail="No change detected.")
    prediction = await repository.prediction_for_revision(session, original.id)
    if prediction is not None and prediction.state != "pending":
        raise HTTPException(409, detail="Reopen prediction before editing")
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
            text=original.text, notes=original.notes,
            review_notes=request.notes if request.notes is not None else original.review_notes,
            annotator_id=original.annotator_id,
            recommended_action=original.recommended_action, confidence=original.confidence,
            scored_at=original.scored_at,
            annotation_id=original.annotation_id,
            source_updated_at=original.source_updated_at)
        session.add(successor)
    successor.source_task_id = original.source_task_id or original.label_id
    successor.notes = original.notes
    if request.notes is not None:
        successor.review_notes = request.notes
    successor.source_updated_at = original.source_updated_at
    successor.prior_revision_id = str(original.id)
    successor.revision_actor = session.info.get("actor_tenant_id", tenant)
    actor_key_id = session.info.get("actor_key_id")
    if actor_key_id is None:
        raise HTTPException(401, "Authenticated actor is unavailable")
    successor.revision_by_key_id = actor_key_id
    successor.revision_at = now
    successor.idempotency_token = request.idempotency_token
    original.superseded_by = successor_label_id
    await session.flush()
    if prediction is not None:
        prediction.current_label_log_id = successor.id
        prediction.decision_version += 1
    if edited_spans is not None:
        await repository.record_label_content(session, successor.id, "text_ner", edited_spans, [], None)
    elif request.tags is not None:
        await repository.record_label_content(session, successor.id, "text_multilabel", [], request.tags, None)
    else:
        await repository.copy_label_content(session, original.id, successor.id)
    await commit_write(session)
    return {"label_id": label_id, "category": request.category,
            "revision_id": str(successor.id), "previous_category": prior_category}


def image_content_exists():
    """Project media kind without reading the stored image or its signed URL."""
    return select(LabelContent.id).where(LabelContent.label_log_id == LabelLog.id,
                                         LabelContent.content_type == "image_classification").exists()


@router.get("/{domain_id}/pending")
@limiter.limit("60/minute")
async def pending(request: Request, domain_id: str, response: Response, session: Session, tenant: ProjectTenant,
                  category: str | None = None, limit: int = Query(default=50, ge=1, le=200),
                  offset: int = Query(default=0, ge=0),
                  sort_by: Literal["label_id", "category", "annotator_id", "confidence", "recommended_action", "scored_at"] | None = None,
                  sort_order: Literal["asc", "desc"] = "asc",
                  search: str | None = Query(default=None, max_length=200)) -> list[dict]:
    domain_id = selected_domain_id(session, tenant, domain_id)
    if await repository.get_domain(session, domain_id) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    filters = [LabelLog.domain_id == domain_id, LabelLog.tenant_id == tenant,
               LabelLog.verified_at.is_(None), LabelLog.scored_at.is_not(None),
               LabelLog.superseded_by.is_(None),
               ~select(Prediction.id).where(Prediction.current_label_log_id == LabelLog.id,
                                            Prediction.state != "pending").exists()]
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
    query = select(LabelLog, image_content_exists()).where(*filters)
    if sort_by is None:
        query = query.order_by(LabelLog.confidence.asc(), LabelLog.scored_at.asc(), LabelLog.id.asc())
    else:
        column = getattr(LabelLog, sort_by)
        ordered = column.desc() if sort_order == "desc" else column.asc()
        query = query.order_by(ordered.nulls_last(), LabelLog.scored_at.asc(), LabelLog.id.asc())
    query = query.offset(offset).limit(limit)
    rows = await session.execute(query)
    return [{"label_id": row.label_id, "category": row.category, "media_kind": "image" if image else "text",
             "annotator_id": row.annotator_id, "confidence": row.confidence,
             "recommended_action": row.recommended_action, "factors": row.factors_json,
             "text_preview": row.text[:80] if row.text is not None else None,
             "notes": row.notes, "review_notes": row.review_notes}
            for row, image in rows]


async def _current_label(session: AsyncSession, domain_id: str, label_id: str,
                         tenant: str, *, lock: bool = False) -> LabelLog:
    scoped = selected_domain_id(session, tenant, domain_id)
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
                               session: Session, tenant: ProjectTenant) -> dict[str, str | int]:
    domain = await repository.get_domain(session, selected_domain_id(session, tenant, domain_id))
    if domain is None:
        raise HTTPException(404, detail="Domain not found")
    await require_active_project(session, domain)
    row = await _current_label(session, domain_id, label_id, tenant, lock=True)
    prediction = await repository.prediction_for_revision(session, row.id)
    if row.verified_at is not None or prediction is not None:
        raise HTTPException(409, detail="Create a revision to edit reviewed or predicted content")
    if await repository.get_label_content(session, row.id) is not None:
        raise HTTPException(409, detail="Content already exists for this revision")
    validate_media_for_project(domain, payload.content_type, payload.image_url,
                               tags=bool(payload.tags), spans=bool(payload.spans))
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
    await commit_write(session)
    return {"label_id": row.label_id, "content_type": payload.content_type,
            count_key: len(spans) if count_key == "spans_count" else len(payload.tags)}


@router.get("/{domain_id}/items/{label_id}")
@router.get("/{domain_id}/{label_id}")
@limiter.limit("60/minute")
async def label_detail(request: Request, response: Response, domain_id: str, label_id: str,
                       session: Session, tenant: ProjectTenant) -> dict:
    row = await _current_label(session, domain_id, label_id, tenant)
    previous_category = None
    if row.prior_revision_id is not None:
        prior = await session.scalar(select(LabelLog).where(
            LabelLog.domain_id == selected_domain_id(session, tenant, domain_id),
            LabelLog.tenant_id == tenant, LabelLog.id == UUID(row.prior_revision_id)))
        previous_category = prior.category if prior and prior.category != row.category else None
    content = await repository.get_label_content(session, row.id)
    prediction = await repository.prediction_for_revision(session, row.id)
    response.headers["Cache-Control"] = "private, no-store"
    original = dict(prediction.original_content) if prediction else {}
    typed = original.get("content")
    if prediction and isinstance(typed, dict) and isinstance(typed.get("image_url"), dict):
        source = await repository.get_label_content(session, prediction.original_label_log_id)
        if source is None:
            raise HTTPException(409, "Original prediction content unavailable")
        original["content"] = {**typed, "image_url": source.image_url}
    return {**({"prediction": {**_prediction_payload(prediction), "original_content": original,
                               "original_category": prediction.original_category}} if prediction else {}),
            "domain_id": domain_id, "label_id": row.label_id, "category": row.category,
            "annotator_id": row.annotator_id, "factors": row.factors_json,
            "recommended_action": row.recommended_action, "confidence": row.confidence,
            "text": row.text, "actual_action": row.actual_action,
            "notes": row.notes, "review_notes": row.review_notes,
            "verified_outcome": row.verified_outcome,
            "verified_at": row.verified_at.isoformat() if row.verified_at else None,
            "revision_id": str(row.id), "previous_category": previous_category,
            "status": "pending_classification" if row.scored_at is None else "scored",
            "content": None if content is None else {
                "content_type": content.content_type, "spans": content.spans_json,
                "tags": content.tags_json, "image_url": content.image_url}}


@autonomy_router.get("/{domain_id}/autonomy")
@limiter.limit("60/minute")
async def domain_autonomy(request: Request, domain_id: str, session: Session, tenant: ProjectTenant) -> dict:
    public_domain_id = domain_id
    domain_id = selected_domain_id(session, tenant, domain_id)
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


EXPORT_TIMEOUT_SECONDS = 300.0
EXPORT_MAX_DOCUMENTS = 5_000
EXPORT_MAX_TEXT_BYTES = 16 * 1024 * 1024
EXPORT_MEDIA_MAX_BYTES = 32 * 1024 * 1024
EXPORT_BROWSER_MAX_BYTES = 32 * 1024 * 1024


class PredictionItem(MediaInput):
    label_id: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=200)
    model_version: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=200)
    annotator_id: str = Field(min_length=1, max_length=200)
    factors: dict[str, float] = Field(min_length=2, max_length=20)
    model_confidence: float = Field(ge=0, le=1)
    text: str | None = None

    @field_validator("label_id", "source", "model_version", "category", "annotator_id")
    @classmethod
    def valid_prediction_identifier(cls, value: str) -> str:
        if not value.strip() or "|" in value:
            raise ValueError("Prediction identifiers must be nonempty and cannot contain |")
        return value

    @field_validator("factors")
    @classmethod
    def valid_prediction_factors(cls, factors: dict[str, float]) -> dict[str, float]:
        return IngestItem.valid_factors(factors)

    @field_validator("text")
    @classmethod
    def valid_prediction_text(cls, value: str | None) -> str | None:
        return IngestItem.valid_text(value)


    @model_validator(mode="after")
    def validate_content_shape(self) -> PredictionItem:
        content = self.content
        if content is None:
            return self
        if content.content_type == "text_ner":
            if self.text is None or content.tags or content.image_url:
                raise ValueError("NER requires source text and spans only")
            previous_end = 0
            for span in sorted(content.spans, key=lambda entry: entry.start):
                if (span.start < previous_end or span.start >= span.end or span.end > len(self.text)
                        or self.text[span.start:span.end] != span.text):
                    raise ValueError("Invalid NER span")
                previous_end = span.end
        elif content.content_type == "text_multilabel":
            if content.spans or content.image_url:
                raise ValueError("Multilabel content accepts only tags")
        elif content.spans or content.tags or not content.image_url:
            raise ValueError("Image content requires an HTTPS URL")
        return self


class PredictionImportRequest(MediaBatch):
    item_model = PredictionItem
    request_key: str = Field(min_length=1, max_length=200)
    items: list[PredictionItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_labels(self) -> PredictionImportRequest:
        if len({item.label_id for item in self.items}) != len(self.items):
            raise ValueError("Prediction label IDs must be unique")
        return self


class PredictionReviewRequest(RevisionRequest):
    assessment: Literal["correct", "incorrect", "unknown"] | None = None
    action: Literal["accept", "correct"] | None = None
    category: str | None = Field(default=None, min_length=1, max_length=200)
    actual_action: str | None = Field(default=None, min_length=1, max_length=200)
    verified_outcome: bool | None = None
    human_spans_reviewed: bool = False
    expected_revision: UUID
    decision_version: int = Field(ge=1)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def explicit_review_operation(self) -> "PredictionReviewRequest":
        if self.assessment is None and self.action is None:
            raise ValueError("Supply an assessment or review action")
        if self.action and self.assessment is not None:
            raise ValueError("Use either a review action or an assessment")
        if self.action == "accept" and (self.category is not None or self.actual_action is not None):
            raise ValueError("Use correct to change the category or action")
        if self.action == "correct" and self.category is None and self.actual_action is None:
            raise ValueError("Correct requires a category or actual_action")
        return self


class PredictionReopenRequest(RevisionRequest):
    expected_revision: UUID
    decision_version: int = Field(ge=1)


class NextBatchItem(BaseModel):
    id: str
    media_kind: Literal["text", "image"]
    text_preview: str
    centroid_distance: float | None
    category: str
    priority_rank: int
    annotator_id: str | None = None
    recommended_action: str
    confidence: float
    notes: str | None = None
    review_notes: str | None = None


class NextBatchResponse(BaseModel):
    items: list[NextBatchItem]
    strategy: Literal["centroid_distance", "random"]
    total_pending: int
    note: str | None = None


class SlaResponse(BaseModel):
    floor_pct: float | None
    current_accuracy: float
    margin: float | None
    gate_status: Literal["safe", "warning", "critical", "paused", "inactive"]
    auto_approve_active: bool
    verified_count: int
    min_verified_for_sla: int


def _nearest_centroid_distance(engine: JudgmentMemoryEngine, factors: dict[str, float],
                               category: str) -> float | None:
    """Use the engine's factor ordering and L2 primitive without scoring side effects."""
    vector = [factors.get(name, 0.5) for name in engine.config.factors]
    if not all(isinstance(value, (int, float)) and isfinite(value) and 0 <= value <= 1 for value in vector):
        return None
    distances = [engine._l2_distance(vector, centroid) for action in engine.config.actions
                 if (centroid := engine.centroids.get(f"{category}|{action}")) is not None
                 and len(centroid) == len(vector)
                 and all(isinstance(v, (int, float)) and isfinite(v) and 0 <= v <= 1 for v in centroid)]
    return min(distances, default=None)


def _utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_csv(value: object) -> object:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + value
    return value


async def _project_for_product(session: AsyncSession, tenant: str, project_id: str,
                               *, write: bool = False) -> Domain:
    domain = await repository.get_domain(session, selected_domain_id(session, tenant, project_id))
    if domain is None:
        raise HTTPException(404, detail="Project not found")
    if write:
        await require_active_project(session, domain)
    return domain


@project_meta_router.get("/next-batch", response_model=NextBatchResponse)
async def next_batch(domain_id: str, tenant: ProjectTenant, session: Session,
                     strategy: str = Query(default="centroid_distance", max_length=50),
                     n: int = Query(default=50, ge=1), offset: int = Query(default=0, ge=0),
                     category: str | None = Query(default=None, max_length=200),
                     search: str | None = Query(default=None, max_length=200)) -> NextBatchResponse:
    """Rank pending labels by their distance from the nearest learned centroid."""
    if strategy != "centroid_distance":
        raise HTTPException(400, detail={
            "message": "Unsupported sampling strategy",
            "supported_strategies": ["centroid_distance"],
        })
    domain = await _project_for_product(session, tenant, domain_id)
    limit = min(n, 200)
    engines = {owner: JudgmentMemoryEngine.from_state(state) for owner, state in
               (await session.execute(select(Engine.annotator_id, Engine.state_json).where(
                   Engine.domain_id == domain.domain_id, Engine.tenant_id == tenant))).all()}
    active = sum(engine.conservation.total_verified for engine in engines.values()) >= 20
    filters = [LabelLog.domain_id == domain.domain_id, LabelLog.tenant_id == tenant,
               LabelLog.scored_at.is_not(None), LabelLog.verified_at.is_(None),
               LabelLog.superseded_by.is_(None), LabelLog.category.is_not(None),
               LabelLog.recommended_action.is_not(None), LabelLog.confidence.is_not(None),
               ~select(Prediction.id).where(Prediction.current_label_log_id == LabelLog.id,
                                            Prediction.state != "pending").exists()]
    if category is not None:
        filters.append(LabelLog.category == category)
    if search and search.strip():
        needle = search.strip().lower()
        filters.append(or_(*(func.lower(field).contains(needle, autoescape=True)
                             for field in (LabelLog.label_id, LabelLog.category,
                                           LabelLog.text, LabelLog.annotator_id))))
    # Fetch only the preview and ranking inputs. Never materialize full source documents.
    rows = await session.stream(select(LabelLog.label_id, LabelLog.annotator_id,
        LabelLog.category, LabelLog.factors_json, LabelLog.recommended_action, LabelLog.confidence,
        LabelLog.notes, LabelLog.review_notes, image_content_exists().label("is_image"),
        func.substr(LabelLog.text, 1, 100).label("preview")).where(*filters).execution_options(yield_per=500))
    ranked: list[tuple[float, str, NextBatchItem]] = []
    total_pending = 0
    async for row in rows:
        total_pending += 1
        engine = engines.get(row.annotator_id)
        distance = (_nearest_centroid_distance(engine, row.factors_json, row.category)
                    if active and engine is not None else None)
        tie = hashlib.sha256(f"{domain.id}:{row.label_id}".encode()).hexdigest()
        item = NextBatchItem(id=row.label_id, media_kind="image" if row.is_image else "text",
                             category=row.category, text_preview=row.preview or "",
                             centroid_distance=round(distance, 6) if distance is not None else None,
                             priority_rank=0, annotator_id=row.annotator_id,
                             recommended_action=row.recommended_action, confidence=row.confidence,
                             notes=row.notes, review_notes=row.review_notes)
        entry = (distance if distance is not None else float("-inf"), tie, item)
        if len(ranked) < offset + limit:
            heapq.heappush(ranked, entry)
        else:
            heapq.heappushpop(ranked, entry)
    ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    page = [entry[2] for entry in ranked[offset:offset + limit]]
    for rank, item in enumerate(page, start=offset + 1):
        item.priority_rank = rank
    return NextBatchResponse(items=page, strategy="centroid_distance" if active else "random",
                             total_pending=total_pending,
                             note=None if active else "Smart sampling activates after 20 verified labels")


@project_meta_router.get("/sla", response_model=SlaResponse)
async def project_sla(domain_id: str, tenant: ProjectTenant, session: Session) -> SlaResponse:
    """Summarize effective human evidence across all annotators in the project."""
    domain = await _project_for_product(session, tenant, domain_id)
    evidence = select(LabelLog.category, LabelLog.verified_outcome,
        func.row_number().over(order_by=(LabelLog.verified_at.desc(), LabelLog.id)).label("position")
    ).where(LabelLog.domain_id == domain.domain_id, LabelLog.tenant_id == tenant,
            LabelLog.verified_at.is_not(None), LabelLog.verified_outcome.is_not(None),
            repository.active_verified_evidence(domain.domain_id, tenant)).subquery()
    metrics = select(
        func.count().label("verified"), func.count(func.distinct(evidence.c.category)).label("covered"),
        func.avg(case((evidence.c.verified_outcome.is_(True), 1.0), else_=0.0))
            .filter(evidence.c.position <= ConservationState().window_size).label("accuracy")
    ).select_from(evidence).subquery()
    # One statement gives the evidence and conservation gates the same PostgreSQL snapshot.
    snapshot = (await session.execute(select(metrics, Engine.state_json).select_from(metrics)
        .outerjoin(Engine, (Engine.domain_id == domain.domain_id) & (Engine.tenant_id == tenant)))).all()
    count, covered, accuracy, _ = snapshot[0]
    current = float(accuracy or 0) * 100
    minimum = 50
    if count < minimum:
        return SlaResponse(floor_pct=None, current_accuracy=round(current, 1), margin=None,
                           gate_status="inactive", auto_approve_active=False, verified_count=count,
                           min_verified_for_sla=minimum)
    config = DomainConfig.from_dict(domain.config_json)
    coverage = covered / max(config.n_categories, 1)
    floor = 100 * 23.53 / max(coverage * count, .001)
    margin = current - floor
    states = (row.state_json for row in snapshot if row.state_json is not None)
    gates_pass = all(JudgmentMemoryEngine.from_state(state).conservation.check_gate(config.n_categories)[0]
                     for state in states)
    if not gates_pass or margin < 0:
        status: Literal["safe", "warning", "critical", "paused", "inactive"] = "paused"
    elif margin > 10:
        status = "safe"
    elif margin >= 5:
        status = "warning"
    else:
        status = "critical"
    payer = await session.get(ApiKey, session.info["payer_key_id"])
    automation_available = (domain.status == "active" and domain.automation_enabled
                            and payer is not None and effective_state(payer) == "active"
                            and payer.tier in {"starter", "professional", "business", "scale", "enterprise"})
    return SlaResponse(floor_pct=round(floor, 1), current_accuracy=round(current, 1),
                       margin=round(margin, 1), gate_status=status,
                       auto_approve_active=bool(automation_available and status != "paused"),
                       verified_count=count, min_verified_for_sla=minimum)


async def _claim_export_slot(session: AsyncSession, project_id: UUID) -> tuple[int, UUID]:
    values = [{"project_id": project_id, "slot": slot} for slot in (1, 2)]
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(pg_insert(ProjectExportSlot).values(values).on_conflict_do_nothing(
            index_elements=[ProjectExportSlot.project_id, ProjectExportSlot.slot]))
    else:
        await session.execute(sqlite_insert(ProjectExportSlot).values(values).on_conflict_do_nothing(
            index_elements=[ProjectExportSlot.project_id, ProjectExportSlot.slot]))
    now = datetime.now(timezone.utc)
    statement = (select(ProjectExportSlot).where(
        ProjectExportSlot.project_id == project_id,
        or_(ProjectExportSlot.lease_token.is_(None), ProjectExportSlot.expires_at <= now))
        .order_by(ProjectExportSlot.slot).limit(1).with_for_update())
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    slot = await session.scalar(statement)
    if slot is None:
        raise HTTPException(429, detail="Both export slots are busy")
    token = uuid4()
    slot.lease_token = token
    slot.expires_at = now + timedelta(seconds=EXPORT_TIMEOUT_SECONDS)
    await commit_write(session)
    return slot.slot, token


async def _release_export_slot(project_id: UUID, slot: int, token: UUID) -> None:
    async with connection.AsyncSessionLocal() as session:
        await session.execute(update(ProjectExportSlot).where(
            ProjectExportSlot.project_id == project_id, ProjectExportSlot.slot == slot,
            ProjectExportSlot.lease_token == token).values(lease_token=None, expires_at=None))
        await session.commit()


def _export_columns(image: bool, include_factors: bool) -> list[str]:
    fields = ["root_label_id", "current_label_id", "source", "text"]
    if image:
        fields.append("image_url")
    fields.extend(("category", "annotator_id", "notes", "review_notes", "recommended_action",
                   "actual_action", "verified_outcome", "confidence", "scored_at", "verified_at",
                   "revision_at", "content", "review_state", "model_confidence", "dlj_confidence",
                   "human_spans_reviewed"))
    if image:
        fields.append("revision_history")
    if include_factors:
        fields.append("factors")
    return fields


async def _export_rows(tenant: str, domain: Domain, *, actor: UUID, review_status: str | None,
                       category: str | None, annotator: str | None,
                       date_from: datetime | None, date_to: datetime | None,
                       include_factors: bool, ner_only: bool, started: float) -> AsyncIterator[dict]:
    count = 0
    text_bytes = 0
    minimum_media_bytes = 0
    async with connection.AsyncSessionLocal() as session:
        session.info["tenant_id"] = tenant
        if session.get_bind().dialect.name == "postgresql":
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            await session.execute(text("SET TRANSACTION READ ONLY"))
        key = await session.get(ApiKey, actor)
        if key is None or not key.is_active or key.reproof_required:
            raise HTTPException(401, "Credential changed before export")
        if key.tenant_id != tenant and not await session.scalar(select(ProjectMember.project_id).where(
                ProjectMember.project_id == domain.id, ProjectMember.member_tenant_id == key.tenant_id,
                ProjectMember.active.is_(True), ProjectMember.role.in_(("reviewer", "admin")))):
            raise HTTPException(403, "Project membership changed before export")
        policy = await session.get(Domain, domain.id)
        if policy is None or (policy.content_type, policy.label_schema, policy.modality_enforced) != (
                domain.content_type, domain.label_schema, domain.modality_enforced):
            raise HTTPException(409, "Project modality changed before export")
        image_project = policy.content_type == "image"
        byte_length = func.octet_length if session.get_bind().dialect.name == "postgresql" else func.length
        last_id: UUID | None = None
        while True:
            if monotonic() - started > EXPORT_TIMEOUT_SECONDS:
                raise HTTPException(504, detail="Export exceeded the five-minute deadline")
            statement = (select(LabelLog.id, LabelLog.prior_revision_id,
                                byte_length(LabelContent.image_url).label("media_bytes"),
                                byte_length(LabelLog.text).label("text_bytes"))
                .outerjoin(LabelContent, LabelContent.label_log_id == LabelLog.id)
                .outerjoin(Prediction, Prediction.current_label_log_id == LabelLog.id)
                .where(LabelLog.domain_id == domain.domain_id, LabelLog.tenant_id == tenant,
                       LabelLog.superseded_by.is_(None)))
            if ner_only:
                statement = statement.where(LabelContent.content_type == "text_ner")
            if category is not None:
                statement = statement.where(LabelLog.category == category)
            if annotator is not None:
                statement = statement.where(LabelLog.annotator_id == annotator)
            stamp = LabelLog.scored_at
            if date_from is not None:
                statement = statement.where(stamp >= date_from)
            if date_to is not None:
                statement = statement.where(stamp < date_to)
            if review_status == "verified":
                statement = statement.where(LabelLog.verified_at.is_not(None))
            elif review_status == "pending":
                statement = statement.where(LabelLog.scored_at.is_not(None), LabelLog.verified_at.is_(None),
                                            or_(Prediction.id.is_(None), Prediction.state == "pending"))
            elif review_status == "unclassified":
                statement = statement.where(LabelLog.scored_at.is_(None))
            elif review_status == "overridden":
                statement = statement.where(LabelLog.verified_at.is_not(None),
                                            LabelLog.actual_action != LabelLog.recommended_action)
            elif review_status in {"auto_approved", "human_reviewed"}:
                statement = statement.where(Prediction.state == review_status)
            if last_id is not None:
                statement = statement.where(LabelLog.id > last_id)
            keys = (await session.execute(statement.order_by(LabelLog.id).limit(500))).all()
            if not keys:
                break
            # Read only ancestry reachable from the selected page.
            identity: dict[str, tuple[str, str | None]] = {}
            parents = {key.prior_revision_id for key in keys if key.prior_revision_id}
            while parents:
                ancestors = (await session.execute(select(
                    LabelLog.id, LabelLog.label_id, LabelLog.prior_revision_id).where(
                    LabelLog.tenant_id == tenant, LabelLog.domain_id == domain.domain_id,
                    LabelLog.id.in_([UUID(value) for value in parents])))).all()
                identity.update({str(a.id): (a.label_id, a.prior_revision_id) for a in ancestors})
                parents = {a.prior_revision_id for a in ancestors if a.prior_revision_id} - identity.keys()
            # Keep cursor pages small even for 10 MiB inline references. Fetch a
            # large image alone, and omit the immutable prediction content snapshot.
            offset = 0
            while offset < len(keys):
                ids: list[UUID] = []
                page_bytes = 0
                while offset < len(keys):
                    entry = keys[offset]
                    media_bytes = entry.media_bytes or 0
                    size = media_bytes + (entry.text_bytes or 0)
                    if ids and page_bytes + size > 512 * 1024:
                        break
                    minimum_media_bytes += media_bytes * (2 if image_project else 1)
                    if minimum_media_bytes > EXPORT_MEDIA_MAX_BYTES:
                        raise HTTPException(413, "Export exceeds the media output cap")
                    text_bytes += entry.text_bytes or 0
                    count += 1
                    if count > EXPORT_MAX_DOCUMENTS or text_bytes > EXPORT_MAX_TEXT_BYTES:
                        raise HTTPException(413, "Export exceeds the project size cap")
                    ids.append(entry.id)
                    offset += 1
                    page_bytes += size
                rows = (await session.execute(select(LabelLog, LabelContent, Prediction)
                    .outerjoin(LabelContent, LabelContent.label_log_id == LabelLog.id)
                    .outerjoin(Prediction, Prediction.current_label_log_id == LabelLog.id)
                    .options(defer(Prediction.original_content))
                    .where(LabelLog.id.in_(ids), LabelLog.tenant_id == tenant,
                           LabelLog.domain_id == domain.domain_id).order_by(LabelLog.id))).all()
                for row, content, prediction in rows:
                    history = [row.label_id]
                    prior = row.prior_revision_id
                    seen: set[str] = set()
                    while prior and prior in identity and prior not in seen:
                        seen.add(prior)
                        label_id, prior = identity[prior]
                        history.append(label_id)
                    content_payload = None if content is None else {
                        "content_type": content.content_type, "spans": content.spans_json,
                        "tags": content.tags_json, "image_url": content.image_url,
                    }
                    item = {
                        "root_label_id": history[-1], "current_label_id": row.label_id,
                        "source": prediction.source if prediction is not None else row.annotation_id or row.source_task_id,
                        "text": row.text, "category": row.category, "annotator_id": row.annotator_id,
                        "notes": row.notes, "review_notes": row.review_notes,
                        "recommended_action": row.recommended_action, "actual_action": row.actual_action,
                        "verified_outcome": row.verified_outcome, "confidence": row.confidence,
                        "scored_at": _utc(row.scored_at), "verified_at": _utc(row.verified_at),
                        "revision_at": _utc(row.revision_at), "content": content_payload,
                        "review_state": prediction.state if prediction is not None else
                                        "verified" if row.verified_at is not None else
                                        "pending" if row.scored_at is not None else "unclassified",
                        "model_confidence": prediction.model_confidence if prediction is not None else None,
                        "dlj_confidence": prediction.dlj_confidence if prediction is not None else row.confidence,
                        "human_spans_reviewed": (prediction.human_spans_reviewed
                                                 if prediction is not None else row.verified_at is not None),
                    }
                    if image_project:
                        item["image_url"] = (content.image_url or None) if content else None
                        item["revision_history"] = list(reversed(history))
                    if include_factors:
                        item["factors"] = row.factors_json
                    yield item
            last_id = keys[-1].id


def _encode_docbin(rows: list[dict], deadline: float) -> bytes:
    try:
        import spacy  # type: ignore[import]
        from spacy.tokens import DocBin  # type: ignore[import]
    except ImportError:
        raise HTTPException(501, detail="DocBin export requires the optional spaCy dependency") from None
    nlp = spacy.blank("en")
    docs = DocBin(store_user_data=True)
    for row in rows:
        if monotonic() >= deadline:
            raise TimeoutError
        doc = nlp.make_doc(row["text"] or "")
        content = row["content"] or {}
        spans = content.get("spans", [])
        if not row["human_spans_reviewed"]:
            raise HTTPException(422, detail="DocBin NER spans require human adjudication")
        entities = []
        for span in spans:
            entity = doc.char_span(span["start"], span["end"], label=span["label"], alignment_mode="strict")
            if entity is None:
                raise HTTPException(422, detail="NER span does not align with the English tokenizer")
            entities.append(entity)
        doc.ents = entities
        doc.user_data["dlj"] = row
        docs.add(doc)
    return docs.to_bytes()


@project_meta_router.get("/export")
async def export_project(domain_id: str, tenant: ProjectTenant, session: Session,
                         format: Literal["jsonl", "csv", "docbin"] = "jsonl",
                         review_status: Literal["pending", "verified", "auto_approved", "human_reviewed",
                                                "unclassified", "overridden"] | None = None,
                         category: str | None = Query(default=None, max_length=200),
                         annotator: str | None = Query(default=None, max_length=200),
                         date_from: datetime | None = None, date_to: datetime | None = None,
                         include_factors: bool = False, browser_fallback: bool = False) -> StreamingResponse:
    if date_from is not None and date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=timezone.utc)
    if date_to is not None and date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=timezone.utc)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, detail="date_from must not be after date_to")
    if format == "docbin" and review_status not in {None, "verified", "overridden"}:
        raise HTTPException(422, detail="DocBin requires verified or overridden labels")
    if EXPORT_TIMEOUT_SECONDS <= 0:
        raise HTTPException(504, detail="Export exceeded the five-minute deadline")
    domain = await _project_for_product(session, tenant, domain_id)
    await lock_tenant(session, domain.tenant_id)
    refreshed_domain = await session.get(Domain, domain.id, with_for_update=True, populate_existing=True)
    if refreshed_domain is None:
        raise HTTPException(404, detail="Project not found")
    domain = refreshed_domain
    actor_tenant = session.info.get("actor_tenant_id", tenant)
    if actor_tenant != domain.tenant_id:
        member = await session.scalar(select(ProjectMember).where(
            ProjectMember.project_id == domain.id,
            ProjectMember.member_tenant_id == actor_tenant,
            ProjectMember.active.is_(True)).with_for_update().execution_options(populate_existing=True))
        if member is None:
            raise HTTPException(403, detail="Project membership changed")
        if member.role == "annotator":
            raise HTTPException(403, detail="Project role does not allow export")
    image_project = domain.content_type == "image"
    if format == "docbin" and domain.modality_enforced and (
            image_project or domain.label_schema != "ner"):
        raise HTTPException(422, "DocBin requires a text NER project")
    # An image CSV is also an import file. Its original decision inputs are required.
    factors = include_factors or (image_project and format == "csv")
    slot, token = await _claim_export_slot(session, domain.id)
    started = monotonic()
    spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
    media_type, extension = {"jsonl": ("application/x-ndjson", "jsonl"),
                             "csv": ("text/csv", "csv"),
                             "docbin": ("application/octet-stream", "spacy")}[format]
    try:
        async with asyncio.timeout(EXPORT_TIMEOUT_SECONDS):
            documents: list[dict] = []
            writer = None
            csv_buffer = io.StringIO(newline="")
            media_output = image_project
            if format == "csv":
                writer = csv.DictWriter(csv_buffer, fieldnames=_export_columns(image_project, factors))
            async for row in _export_rows(tenant, domain, actor=session.info["actor_key_id"],
                                          review_status=("verified" if format == "docbin" and review_status is None else review_status), category=category,
                                          annotator=annotator, date_from=date_from, date_to=date_to,
                                          include_factors=factors, ner_only=format == "docbin",
                                          started=started):
                url = (row["content"] or {}).get("image_url")
                if url:
                    media_output = True
                    # UTF-8 size and CSV/JSON escaping can only increase this lower bound.
                    if spool.tell() + len(url) * (2 if image_project else 1) > EXPORT_MEDIA_MAX_BYTES:
                        raise HTTPException(413, "Export exceeds the media output cap")
                if format == "jsonl":
                    encoded_row = (json.dumps(row, ensure_ascii=False) + "\n").encode()
                elif format == "csv":
                    assert writer is not None
                    if spool.tell() == 0:
                        writer.writeheader()
                    cells: dict[str, object] = {}
                    for name, value in row.items():
                        # Escape literal leading apostrophes as well as formula prefixes
                        # so image CSV imports can restore both cases without ambiguity.
                        if image_project and isinstance(value, str) and value.startswith("'"):
                            cells[name] = "'" + value
                        else:
                            cells[name] = _safe_csv(json.dumps(value) if isinstance(value, (dict, list)) else value)
                    writer.writerow(cells)
                    encoded_row = csv_buffer.getvalue().encode()
                    csv_buffer.seek(0)
                    csv_buffer.truncate()
                else:
                    documents.append(row)
                    continue
                if media_output and spool.tell() + len(encoded_row) > EXPORT_MEDIA_MAX_BYTES:
                    raise HTTPException(413, "Export exceeds the media output cap")
                spool.write(encoded_row)
            if format == "docbin":
                encoded = await asyncio.to_thread(_encode_docbin, documents, started + EXPORT_TIMEOUT_SECONDS)
                spool.write(encoded)
            elif writer is not None and spool.tell() == 0:
                # Preserve the historical empty text CSV header. Image exports
                # always have the same importable header, including on an empty page.
                fields = _export_columns(image_project, factors)
                if not image_project:
                    fields = [field for field in fields if field not in ("notes", "review_notes")]
                csv.writer(csv_buffer).writerow(fields)
                spool.write(csv_buffer.getvalue().encode())
        if browser_fallback and spool.tell() > EXPORT_BROWSER_MAX_BYTES:
            raise HTTPException(413, "Export exceeds browser fallback capacity")
        if monotonic() - started >= EXPORT_TIMEOUT_SECONDS:
            raise HTTPException(504, "Export exceeded the five-minute deadline")
        spool.seek(0)
    except BaseException as exc:
        spool.close()
        await asyncio.shield(_release_export_slot(domain.id, slot, token))
        if isinstance(exc, TimeoutError):
            raise HTTPException(504, "Export exceeded the five-minute deadline") from None
        raise

    class ExportResponse(StreamingResponse):
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            try:
                async with asyncio.timeout(max(0, EXPORT_TIMEOUT_SECONDS - (monotonic() - started))):
                    await super().__call__(scope, receive, send)
            finally:
                spool.close()
                await asyncio.shield(_release_export_slot(domain.id, slot, token))

    return ExportResponse(iter(lambda: spool.read(65536), b""), media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{domain.id}.{extension}"',
        "Cache-Control": "no-store",
        "X-Export-Lease": str(token),
        "X-DLJ-Content-Type": domain.content_type if domain.modality_enforced else "mixed",
        "X-DLJ-Label-Schema": domain.label_schema if domain.modality_enforced else "mixed",
    })


def _prediction_payload(prediction: Prediction) -> dict:
    return {
        "id": str(prediction.id), "state": prediction.state,
        "current_label_log_id": str(prediction.current_label_log_id),
        "source": prediction.source, "model_version": prediction.model_version,
        "model_confidence": prediction.model_confidence,
        "dlj_confidence": prediction.dlj_confidence,
        "tier": prediction.tier, "recommendation": prediction.recommendation,
        "decision_reason": prediction.decision_reason,
        "decision_version": prediction.decision_version,
        "machine_approved_at": _utc(prediction.machine_approved_at),
        "human_reviewed_at": _utc(prediction.human_reviewed_at),
        "assessment": prediction.assessment,
        "human_spans_reviewed": prediction.human_spans_reviewed,
    }


def _prediction_state(prediction: Prediction) -> str:
    if prediction.state == "pending":
        return "reopened" if prediction.decision_version > 1 else "pending_review"
    if prediction.state == "auto_approved":
        return "accepted"
    if prediction.assessment == "unknown":
        return "unknown"
    return "corrected" if prediction.assessment == "incorrect" else "accepted"


def _prediction_item(prediction: Prediction, row: LabelLog, config: DomainConfig,
                     content: LabelContent | None) -> dict:
    return {
        **_prediction_payload(prediction),
        "prediction_state": _prediction_state(prediction),
        "origin": "prediction", "label_id": row.label_id, "text": row.text,
        "media_kind": "image" if content and content.content_type == "image_classification" else "text",
        "category": row.category, "action": row.actual_action or row.recommended_action,
        "spans": content.spans_json if content and content.content_type == "text_ner" else [],
        "confidence": row.confidence, "factors": row.factors_json,
        "annotator_id": row.annotator_id, "scored_at": _utc(row.scored_at),
        "categories": config.categories, "actions": config.actions,
    }


@project_meta_router.post("/predictions", status_code=201)
async def import_predictions(domain_id: str, payload: PredictionImportRequest,
                             tenant: ProjectTenant, session: Session) -> dict:
    domain = await _project_for_product(session, tenant, domain_id, write=True)
    actor = session.info.get("actor_key_id")
    if actor is None:
        raise HTTPException(401, detail="Authenticated actor is unavailable")
    digest = request_digest(payload.model_dump(mode="json"))
    receipt = await session.get(ProjectRequest, (domain.id, actor, "prediction_import", payload.request_key),
                                with_for_update=True)
    if receipt is not None:
        for index, item in enumerate(payload.items):
            item.check_annotation_fields(domain, index)
        if receipt.payload_digest != digest:
            raise HTTPException(409, detail="Request key was used with different predictions")
        return dict(receipt.result_json)
    config = DomainConfig.from_dict(domain.config_json)
    known = set(config.categories)
    for index, item in enumerate(payload.items):
        prepare_content(domain, item, known, index)
        if item.category not in known or set(item.factors) != set(config.factors):
            raise HTTPException(422, detail=f"Prediction differs from project schema at item {index}")
        if item.content:
            names = {span.label for span in item.content.spans} | set(item.content.tags)
            if names - known:
                raise HTTPException(422, detail=f"Unknown content category at item {index}")
    payer_id = session.info.get("payer_key_id")
    payer = await session.get(ApiKey, payer_id) if payer_id is not None else None
    results: list[dict] = []
    now = datetime.now(timezone.utc)
    for index, item in enumerate(payload.items):
        try:
            scored = await _ingest(session, domain.domain_id, IngestItem(
                label_id=item.label_id, category=item.category, annotator_id=item.annotator_id,
                factors=item.factors, text=item.text, content=item.content), domain.public_domain_id)
            row = await session.scalar(select(LabelLog).where(
                LabelLog.domain_id == domain.domain_id, LabelLog.tenant_id == tenant,
                LabelLog.label_id == item.label_id).with_for_update())
            assert row is not None
            original_content = item.content.model_dump(mode="json") if item.content else None
            if original_content and item.content and item.content.decoded_size:
                assert item.content.image_url is not None
                original_content["image_url"] = {"content_ref": str(row.id),
                    "sha256": hashlib.sha256(item.content.image_url.encode("ascii")).hexdigest()}
            verified_count, accuracy = await repository.verified_accuracy(
                session, domain.domain_id, item.category, item.annotator_id)
            profile = await repository.get_annotator(session, domain.domain_id, item.annotator_id)
            named_annotator_eligible = (profile is not None and profile.last_active is not None and
                                        verified_count >= 30 and accuracy is not None and accuracy >= .80)
            paid_tier = payer is not None and effective_state(payer) == "active" and payer.tier in {
                "starter", "professional", "business", "scale", "enterprise"}
            gates = {
                "automation_enabled": domain.automation_enabled,
                "model_confidence": item.model_confidence >= domain.confidence_floor,
                "dlj_confidence": scored.confidence >= .80 and scored.recommended_action == "approve",
                "autonomous_tier": scored.tier == AutonomyTier.AUTONOMOUS.value and paid_tier,
                "conservation_gate": (scored.conservation_status != "paused" and
                                      bool(scored.tier_status.get("conservation_gate_pass"))),
                "named_annotator": named_annotator_eligible,
            }
            auto_approved = all(gates.values())
            reason = "all_gates_passed" if auto_approved else next(name for name, passed in gates.items() if not passed)
            prediction = Prediction(
                project_id=domain.id, original_label_log_id=row.id, current_label_log_id=row.id,
                source=item.source, model_version=item.model_version,
                original_content={"text": item.text,
                                  "content": original_content},
                original_category=item.category, model_confidence=item.model_confidence,
                dlj_confidence=scored.confidence, tier=scored.tier,
                recommendation=scored.recommended_action, gate_snapshot={**scored.tier_status, "automation": gates},
                decision_reason=reason, state="auto_approved" if auto_approved else "pending",
                imported_at=now, machine_approved_at=now if auto_approved else None,
                human_spans_reviewed=False,
            )
            session.add(prediction)
            await session.flush()
            if auto_approved:
                await repository.record_webhook_event(session, domain, "prediction.auto_approved",
                                                      str(prediction.id), {
                    "prediction_id": str(prediction.id), "label_id": row.label_id,
                    "model_version": prediction.model_version,
                    "model_confidence": prediction.model_confidence,
                    "dlj_confidence": prediction.dlj_confidence,
                })
            results.append(_prediction_payload(prediction))
        except (IntegrityError, StaleDataError) as exc:
            raise HTTPException(409, detail=f"Prediction conflict at item {index}") from exc
    result = {"results": results, "batch_size": len(results)}
    session.add(ProjectRequest(project_id=domain.id, actor_key_id=actor,
                               operation="prediction_import", request_key=payload.request_key,
                               payload_digest=digest, result_json=result,
                               expires_at=now + timedelta(days=30)))
    await commit_write(session)
    return result


async def _locked_prediction(session: AsyncSession, domain: Domain, prediction_id: UUID) -> Prediction:
    prediction = await session.scalar(select(Prediction).where(
        Prediction.id == prediction_id, Prediction.project_id == domain.id).with_for_update())
    if prediction is None:
        raise HTTPException(404, detail="Prediction not found")
    return prediction


async def _prediction_source_content(session: AsyncSession, domain: Domain, row: LabelLog) -> LabelContent | None:
    content = await repository.get_label_content(session, row.id)
    url = content.image_url if content else None
    try:
        validate_layout(domain, content.content_type if content else None, bool(url),
                        tags=bool(content and content.tags_json), spans=bool(content and content.spans_json))
        if content is not None and content.content_type == "image_classification":
            if not url or content.tags_json or content.spans_json:
                raise HTTPException(422)
            # Existing inline sources remain valid when new inline uploads are disabled.
            if url.startswith("data:"):
                validate_data_uri(url)
            else:
                validate_image_url(url, strict=domain.modality_enforced)
    except HTTPException:
        raise HTTPException(409, "Source revision has no valid content") from None
    return content


@project_meta_router.post("/predictions/{prediction_id}/review")
async def review_prediction(domain_id: str, prediction_id: UUID, payload: PredictionReviewRequest,
                            tenant: ProjectTenant, session: Session) -> dict:
    """Record explicit human evidence for a pending or machine-approved prediction."""
    domain = await _project_for_product(session, tenant, domain_id, write=True)
    prediction = await _locked_prediction(session, domain, prediction_id)
    if prediction.decision_version != payload.decision_version or prediction.current_label_log_id != payload.expected_revision:
        raise HTTPException(409, detail="Prediction changed; reload and retry")
    if prediction.state == "human_reviewed":
        raise HTTPException(409, detail="Prediction is already reviewed")
    row = await session.scalar(select(LabelLog).where(
        LabelLog.id == prediction.current_label_log_id, LabelLog.domain_id == domain.domain_id,
        LabelLog.tenant_id == tenant).with_for_update())
    if row is None or row.superseded_by is not None:
        raise HTTPException(409, detail="Prediction label revision is stale")
    config = DomainConfig.from_dict(domain.config_json)
    content = await _prediction_source_content(session, domain, row)
    if (content is not None and content.content_type == "text_ner" and content.spans_json
            and not payload.human_spans_reviewed):
        raise HTTPException(422, detail="NER spans require explicit human review")
    assessment = payload.assessment or ("correct" if payload.action == "accept" else "incorrect")
    if payload.category is not None and payload.category not in config.categories:
        raise HTTPException(422, detail="Category is not in this project's schema")
    if payload.action == "correct" and payload.category is not None and payload.category != row.category:
        successor = LabelLog(
            domain_id=row.domain_id, tenant_id=row.tenant_id,
            label_id=f"revision:{uuid4().hex}", annotator_id=row.annotator_id,
            category=payload.category, factors_json=row.factors_json, text=row.text,
            notes=row.notes,
            confidence=row.confidence, recommended_action=row.recommended_action,
            scored_at=row.scored_at, source_updated_at=row.source_updated_at,
        )
        session.add(successor)
        await session.flush()
        successor.annotation_id = row.annotation_id
        successor.source_task_id = row.source_task_id
        successor.prior_revision_id = str(row.id)
        successor.revision_actor = session.info.get("actor_tenant_id", tenant)
        successor.revision_by_key_id = session.info.get("actor_key_id")
        successor.revision_at = datetime.now(timezone.utc)
        row.superseded_by = successor.label_id
        await repository.copy_label_content(session, content, successor.id)
        prediction.current_label_log_id = successor.id
        row = successor
    if assessment != "unknown":
        engine = await repository.load_or_create_engine(session, domain.domain_id, row.annotator_id)
        repository.sync_engine_categories(engine, config.categories)
        if row.recommended_action is None:
            raise HTTPException(409, detail="Prediction has not been scored")
        actual_action = payload.actual_action
        outcome = payload.verified_outcome if payload.verified_outcome is not None else assessment == "correct"
        if actual_action is None:
            actual_action = row.recommended_action if assessment == "correct" else "reject"
        if actual_action not in engine.config.actions:
            raise HTTPException(422, detail="Supply an actual_action from this project's actions")
        await repository.verify_and_learn(session, engine, domain.domain_id, row.label_id,
                                          actual_action, outcome,
                                          "prediction_human_review", payload.notes)
        await repository.record_webhook_event(session, domain, "label.verified", str(row.id), {
            "label_id": row.label_id, "revision_id": str(row.id),
            "actual_action": actual_action,
            "verified_outcome": outcome,
            "prediction_id": str(prediction.id),
        })
    if assessment == "unknown":
        row.verification_reason = "prediction_assessment_unknown"
        row.review_notes = payload.notes
    now = datetime.now(timezone.utc)
    prediction.state = "human_reviewed"
    prediction.human_reviewed_at = now
    prediction.reviewer_key_id = session.info.get("actor_key_id")
    prediction.assessment = assessment
    prediction.human_spans_reviewed = payload.human_spans_reviewed
    prediction.decision_version += 1
    await commit_write(session)
    return _prediction_payload(prediction)


@project_meta_router.post("/predictions/{prediction_id}/reopen")
async def reopen_prediction(domain_id: str, prediction_id: UUID, payload: PredictionReopenRequest,
                            tenant: ProjectTenant, session: Session) -> dict:
    """Append an unverified revision and return a reviewed prediction to the queue."""
    domain = await _project_for_product(session, tenant, domain_id, write=True)
    prediction = await _locked_prediction(session, domain, prediction_id)
    if (prediction.decision_version != payload.decision_version
            or prediction.current_label_log_id != payload.expected_revision):
        raise HTTPException(409, detail="Prediction changed; reload and retry")
    if prediction.state == "pending":
        raise HTTPException(409, detail="Prediction is already pending")
    old = await session.scalar(select(LabelLog).where(
        LabelLog.id == prediction.current_label_log_id, LabelLog.domain_id == domain.domain_id,
        LabelLog.tenant_id == tenant).with_for_update())
    if old is None or old.superseded_by is not None or old.category is None:
        raise HTTPException(409, detail="Prediction label revision is stale")
    content = await _prediction_source_content(session, domain, old)
    new_label_id = f"prediction:{prediction.id.hex}:v{prediction.decision_version + 1}"
    successor = LabelLog(
        domain_id=old.domain_id, tenant_id=old.tenant_id, label_id=new_label_id,
        annotator_id=old.annotator_id, category=old.category, factors_json=old.factors_json,
        text=old.text, notes=old.notes, confidence=old.confidence,
        recommended_action=old.recommended_action,
        scored_at=old.scored_at, source_updated_at=old.source_updated_at)
    session.add(successor)
    await session.flush()
    successor.annotation_id = old.annotation_id
    successor.source_task_id = old.source_task_id
    successor.prior_revision_id = str(old.id)
    successor.revision_actor = session.info.get("actor_tenant_id", tenant)
    successor.revision_by_key_id = session.info.get("actor_key_id")
    successor.revision_at = datetime.now(timezone.utc)
    old.superseded_by = successor.label_id
    await repository.copy_label_content(session, content, successor.id)
    prediction.current_label_log_id = successor.id
    prediction.state = "pending"
    prediction.assessment = None
    prediction.human_reviewed_at = None
    prediction.reviewer_key_id = None
    prediction.human_spans_reviewed = False
    prediction.decision_version += 1
    await commit_write(session)
    return _prediction_payload(prediction)


@project_meta_router.get("/predictions")
async def list_predictions(domain_id: str, tenant: ProjectTenant, session: Session,
                           prediction_state: Literal["pending_review", "accepted", "corrected", "reopened", "unknown"] | None = None,
                           origin: Literal["all", "human", "prediction"] = "prediction",
                           source: str | None = Query(default=None, max_length=200),
                           sort_by: Literal["text", "category", "action", "confidence", "prediction_state", "scored_at"] = "scored_at",
                           sort_order: Literal["asc", "desc"] = "desc",
                           limit: int = Query(50, ge=1, le=200),
                           offset: int = Query(0, ge=0)) -> dict:
    """List prediction provenance joined to its current label revision."""
    domain = await _project_for_product(session, tenant, domain_id)
    visible_state = case(
        (Prediction.id.is_(None), "human"),
        (Prediction.state == "auto_approved", "accepted"),
        ((Prediction.state == "pending") & (Prediction.decision_version > 1), "reopened"),
        (Prediction.state == "pending", "pending_review"),
        (Prediction.assessment == "incorrect", "corrected"),
        (Prediction.assessment == "unknown", "unknown"),
        else_="accepted",
    )
    query = select(LabelLog, Prediction, LabelContent).options(
        defer(Prediction.original_content), defer(LabelContent.image_url)).outerjoin(
        Prediction, (Prediction.current_label_log_id == LabelLog.id) & (Prediction.project_id == domain.id)
    ).outerjoin(LabelContent, LabelContent.label_log_id == LabelLog.id).where(
        LabelLog.tenant_id == tenant, LabelLog.domain_id == domain.domain_id,
        LabelLog.superseded_by.is_(None), LabelLog.scored_at.is_not(None),
        or_(Prediction.id.is_not(None), LabelLog.verified_at.is_(None)),
    )
    if origin == "human":
        query = query.where(Prediction.id.is_(None))
    elif origin == "prediction":
        query = query.where(Prediction.id.is_not(None))
    if source:
        query = query.where(Prediction.source == source)
    if prediction_state:
        query = query.where(visible_state == prediction_state)
    action = func.coalesce(LabelLog.actual_action, LabelLog.recommended_action)
    score = func.coalesce(Prediction.dlj_confidence, LabelLog.confidence)
    columns = {"text": LabelLog.text, "category": LabelLog.category, "action": action,
               "confidence": score, "prediction_state": visible_state, "scored_at": LabelLog.scored_at}
    column = columns[sort_by]
    order = column.asc() if sort_order == "asc" else column.desc()
    total = int(await session.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = await session.execute(query.order_by(order.nulls_last(), LabelLog.id).offset(offset).limit(limit))
    config = DomainConfig.from_dict(domain.config_json)
    items = [_prediction_item(pred, row, config, content) if pred is not None else {
        "origin": "human", "label_id": row.label_id, "text_preview": (row.text or "")[:80],
        "media_kind": "image" if content and content.content_type == "image_classification" else "text",
        "category": row.category, "confidence": row.confidence, "recommended_action": row.recommended_action,
        "scored_at": _utc(row.scored_at),
    } for row, pred, content in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@project_meta_router.get("/predictions/stats")
async def prediction_stats(domain_id: str, tenant: ProjectTenant, session: Session) -> dict:
    """Summarize prediction states, sources and known human accuracy."""
    domain = await _project_for_product(session, tenant, domain_id)
    groups = (await session.execute(select(
        Prediction.state, Prediction.source, Prediction.assessment, func.count()
    ).where(Prediction.project_id == domain.id)
      .group_by(Prediction.state, Prediction.source, Prediction.assessment))).all()
    by_state: dict[str, int] = {}
    by_source: dict[str, int] = {}
    correct = known = 0
    for state, source, assessment, count in groups:
        by_state[state] = by_state.get(state, 0) + count
        by_source[source] = by_source.get(source, 0) + count
        if assessment in {"correct", "incorrect"}:
            known += count
            if assessment == "correct":
                correct += count
    return {"total": sum(by_state.values()), "by_state": by_state, "by_source": by_source,
            "reviewed_known": known, "accuracy": correct / known if known else None}


@project_labels_router.post("")
async def project_import_one(request: Request, domain_id: str, item: ProjectImportItem, session: Session,
                             tenant: ProjectTenant,
                             request_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict:
    if not 0 < len(request_key) <= 200:
        raise HTTPException(422, detail="Idempotency-Key must be 1–200 characters")
    session.info["single_import"] = True
    result = await project_import_batch(request, domain_id,
                                        ProjectImportBatch(request_key=request_key, items=[item]),
                                        session, tenant)
    return dict(result["results"][0])


@project_labels_router.post("/verify", response_model=VerifyResponse)
async def project_verify(domain_id: str, payload: ProjectVerifyInput,
                         session: Session, tenant: ProjectTenant) -> VerifyResponse:
    return await verify(VerifyRequest(domain_id=domain_id, **payload.model_dump()), session, tenant)


# Reuse the transactional legacy handlers after project UUID authorization.
# The path parameter name stays domain_id so the shared dependency resolves
# the immutable project before any handler sees the public alias.
project_labels_router.add_api_route("/bulk-verify", bulk_verify, methods=["POST"])
project_labels_router.add_api_route("/pending", pending, methods=["GET"])
project_labels_router.add_api_route("/sample", seed_sample, methods=["POST"])
project_labels_router.add_api_route("/tasks", create_text_task, methods=["POST"])
project_labels_router.add_api_route("/items/{label_id}/relabel", relabel_item, methods=["POST"])
project_labels_router.add_api_route("/items/{label_id}/content", create_label_content, methods=["POST"])
project_labels_router.add_api_route("/items/{label_id}", label_detail, methods=["GET"])
project_labels_router.add_api_route("/{label_id}", label_detail, methods=["GET"])
project_meta_router.add_api_route("/autonomy", domain_autonomy, methods=["GET"])
project_meta_router.add_api_route("/guidelines", get_guidelines, methods=["GET"])
project_meta_router.add_api_route("/guidelines", put_guidelines, methods=["PUT"])
