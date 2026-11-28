"""Transactional labeling repository. Callers commit or roll back the session."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import and_, bindparam, case, exists, func, insert, or_, select, update
from sqlalchemy.orm import aliased
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.sql.dml import Insert
from sqlalchemy.sql.elements import BindParameter

from jm_core import DomainConfig, JudgmentMemoryEngine, LearnResult, ScoreResult
from db.models import Annotator, Domain, Engine, LabelContent, LabelLog, Prediction, WebhookDelivery, WebhookEndpoint, WebhookEvent


def _tenant(session: AsyncSession) -> str:
    return str(session.info.get("tenant_id", ""))


async def prediction_for_revision(session: AsyncSession, revision: UUID) -> Prediction | None:
    return await session.scalar(select(Prediction).where(Prediction.current_label_log_id == revision))


def record_unassessed_prediction_review(prediction: Prediction, revision: LabelLog) -> None:
    """A generic human verification is evidence about the label only."""
    prediction.current_label_log_id = revision.id
    prediction.state = "human_reviewed"
    prediction.human_reviewed_at = revision.verified_at
    prediction.reviewer_key_id = revision.verified_by_key_id
    prediction.assessment = "unknown"
    prediction.human_spans_reviewed = False
    prediction.decision_version += 1


async def cancel_open_deliveries(session: AsyncSession, endpoint: WebhookEndpoint,
                                 destination_version: int) -> None:
    await session.execute(update(WebhookDelivery).where(
        WebhookDelivery.endpoint_id == endpoint.id,
        WebhookDelivery.destination_version == destination_version,
        WebhookDelivery.state.in_(("pending", "leased"))).values(
            state="cancelled", lease_token=None, lease_until=None, next_attempt_at=None,
            terminal_at=datetime.now(timezone.utc), error_class="destination_changed"))


async def record_webhook_event(session: AsyncSession, domain: Domain, event_type: str,
                               transition_key: str, data: dict) -> WebhookEvent:
    """Append the canonical D/E event in the caller's business transaction."""
    event_id = uuid4()
    occurred_at = datetime.now(timezone.utc)
    if event_type in {"label.verified", "prediction.auto_approved"} and "label_id" in data:
        image = domain.content_type == "image"
        if not domain.modality_enforced:
            image = bool(await session.scalar(select(exists().where(
                LabelLog.tenant_id == domain.tenant_id, LabelLog.domain_id == domain.domain_id,
                LabelLog.label_id == data["label_id"], LabelContent.label_log_id == LabelLog.id,
                LabelContent.image_url.is_not(None)))))
        if image:
            label = quote(data["label_id"], safe="")
            data = {**data, "media_kind": "image",
                    "item_detail_path": f"/v1/projects/{domain.id}/labels/items/{label}"}
    envelope = {
        "event_id": str(event_id),
        "event_type": event_type,
        "project_id": str(domain.id),
        "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
        "schema_version": 1,
        "data": data,
    }
    event = WebhookEvent(
        id=event_id, project_id=domain.id, event_type=event_type,
        transition_key=transition_key, schema_version=1,
        canonical_body=json.dumps(envelope, sort_keys=True, separators=(",", ":")),
        created_at=occurred_at,
    )
    session.add(event)
    await session.flush()
    if event_type != "webhook.test":
        endpoints = await session.scalars(select(WebhookEndpoint).where(
            WebhookEndpoint.project_id == domain.id, WebhookEndpoint.active.is_(True)
        ).order_by(WebhookEndpoint.id).with_for_update())
        for endpoint in endpoints:
            if event_type in endpoint.subscribed_events:
                session.add(WebhookDelivery(endpoint_id=endpoint.id, event_id=event.id,
                    destination_version=endpoint.destination_version, state="pending",
                    attempts=0, next_attempt_at=occurred_at))
    return event


async def create_domain(session: AsyncSession, domain_id: str, domain_name: str,
                        config: DomainConfig, tenant_id: str | None = None,
                        public_domain_id: str | None = None, *, content_type: str = "text",
                        label_schema: str = "single", modality_enforced: bool = False) -> Domain:
    scope = tenant_id if tenant_id is not None else _tenant(session)
    values = dict(domain_id=domain_id, tenant_id=scope, domain_name=domain_name,
                  public_domain_id=public_domain_id, config_json=config.to_dict(),
                  content_type=content_type, label_schema=label_schema,
                  modality_enforced=modality_enforced)
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        pg_statement = pg_insert(Domain).values(**values).on_conflict_do_nothing(
            index_elements=[Domain.domain_id])
        result = await session.execute(pg_statement)
    else:
        sqlite_statement = sqlite_insert(Domain).values(**values).on_conflict_do_nothing(
            index_elements=[Domain.domain_id])
        result = await session.execute(sqlite_statement)
    if getattr(result, "rowcount", None) != 1:
        raise HTTPException(409, detail="Domain already exists")
    domain = await session.scalar(select(Domain).where(Domain.domain_id == domain_id,
                                                      Domain.tenant_id == scope))
    assert domain is not None
    return domain


async def get_domain(session: AsyncSession, domain_id: str, tenant_id: str | None = None) -> Domain | None:
    return await session.scalar(select(Domain).where(Domain.domain_id == domain_id,
                      Domain.tenant_id == (tenant_id if tenant_id is not None else _tenant(session))))


async def list_domains(session: AsyncSession) -> list[Domain]:
    return list((await session.scalars(select(Domain).where(Domain.tenant_id == _tenant(session))
                                      .order_by(Domain.created_at, Domain.domain_id))).all())


def _engine_query(domain_id: str, annotator_id: str | None, tenant_id: str):
    return select(Engine).where(Engine.domain_id == domain_id, Engine.annotator_id == annotator_id,
                                Engine.tenant_id == tenant_id)


async def save_engine_state(session: AsyncSession, domain_id: str, annotator_id: str | None,
                            engine: JudgmentMemoryEngine) -> Engine:
    state = engine.export_state()
    expected = getattr(engine, "_db_version", 0)
    if not expected:
        if await session.scalar(_engine_query(domain_id, annotator_id, _tenant(session)).with_only_columns(Engine.id)) is not None:
            raise StaleDataError("Engine version changed during update")
        row = Engine(domain_id=domain_id, tenant_id=_tenant(session), annotator_id=annotator_id,
                     state_json=state, version=1)
        session.add(row)
        await session.flush()
    else:
        updated = await session.scalar(
            update(Engine).where(Engine.domain_id == domain_id, Engine.annotator_id == annotator_id,
                                 Engine.tenant_id == _tenant(session), Engine.version == expected)
            .values(state_json=state, version=expected + 1, updated_at=datetime.now(timezone.utc))
            .returning(Engine).execution_options(populate_existing=True)
        )
        if updated is None:
            raise StaleDataError("Engine version changed during update")
        row = updated
    setattr(engine, "_db_version", row.version)
    return row


async def load_engine(session: AsyncSession, domain_id: str,
                      annotator_id: str | None = None) -> JudgmentMemoryEngine | None:
    row = await session.scalar(_engine_query(domain_id, annotator_id, _tenant(session)))
    if row is None:
        return None
    engine = JudgmentMemoryEngine.from_state(row.state_json)
    setattr(engine, "_db_version", row.version)
    return engine


async def load_or_create_engine(session: AsyncSession, domain_id: str,
                                annotator_id: str | None = None) -> JudgmentMemoryEngine:
    existing = await load_engine(session, domain_id, annotator_id)
    if existing is not None:
        return existing
    domain = await session.scalar(select(Domain).where(
        Domain.domain_id == domain_id, Domain.tenant_id == _tenant(session)).with_for_update())
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    # The domain lock serializes the first engine writer. A predecessor may
    # have created the engine while this transaction waited for that lock.
    existing = await load_engine(session, domain_id, annotator_id)
    if existing is not None:
        return existing
    return JudgmentMemoryEngine(DomainConfig.from_dict(domain.config_json))


def sync_engine_categories(engine: JudgmentMemoryEngine, categories: list[str]) -> None:
    """Bring an older annotator snapshot up to the stored domain vocabulary."""
    for category in categories:
        if category not in engine.config.categories:
            engine.config.categories.append(category)
        for action in engine.config.actions:
            engine.centroids.setdefault(f"{category}|{action}", [0.5] * engine.config.n_factors)


async def record_score(session: AsyncSession, domain_id: str, label_id: str,
                       annotator_id: str | None, category: str, factors: dict[str, float],
                       recommended_action: str, confidence: float, text: str | None = None,
                       notes: str | None = None) -> LabelLog:
    row = LabelLog(domain_id=domain_id, tenant_id=_tenant(session), label_id=label_id, annotator_id=annotator_id,
                   category=category, factors_json=factors, text=text, notes=notes,
                   recommended_action=recommended_action,
                   confidence=confidence)
    session.add(row)
    await session.flush()
    return row


async def get_label_content(session: AsyncSession, label_log_id: UUID) -> LabelContent | None:
    return await session.scalar(select(LabelContent).where(LabelContent.label_log_id == label_log_id))


async def record_label_content(session: AsyncSession, label_log_id: UUID, content_type: str,
                               spans: list[dict], tags: list[str],
                               image_url: str | None) -> LabelContent:
    row = LabelContent(label_log_id=label_log_id, content_type=content_type,
                       spans_json=spans, tags_json=tags, image_url=image_url)
    session.add(row)
    await session.flush()
    return row


async def copy_label_content(session: AsyncSession, source: UUID | LabelContent | None, target: UUID) -> None:
    """Reuse the validated source when the caller already loaded its media."""
    existing = await get_label_content(session, source) if isinstance(source, UUID) else source
    if existing is not None:
        await record_label_content(session, target, existing.content_type,
                                   existing.spans_json, existing.tags_json, existing.image_url)


async def record_verification(session: AsyncSession, domain_id: str, label_id: str,
                              actual_action: str, verified_outcome: bool,
                              reason: str | None = None,
                              notes: str | None = None) -> LabelLog:
    row = await session.scalar(select(LabelLog).where(LabelLog.domain_id == domain_id,
                                                     LabelLog.tenant_id == _tenant(session),
                                                     LabelLog.label_id == label_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Label not found")
    if row.verified_at is not None:
        raise ValueError("Label already verified")
    row.actual_action = actual_action
    row.verified_outcome = verified_outcome
    row.verified_at = datetime.now(timezone.utc)
    row.verified_by_key_id = session.info.get("actor_key_id") or session.info.get("payer_key_id")
    row.verification_reason = reason
    row.review_notes = notes
    await session.flush()
    return row


def active_verified_evidence(domain_id: str | BindParameter[str], tenant_id: str | BindParameter[str]):
    """Keep the latest verified observation along each revision chain."""
    lineage = select(
        LabelLog.id.label("root_id"), LabelLog.superseded_by.label("next_id"),
        LabelLog.tenant_id.label("tenant_id"), LabelLog.domain_id.label("domain_id"),
    ).where(LabelLog.domain_id == domain_id, LabelLog.tenant_id == tenant_id,
            LabelLog.verified_at.is_not(None), LabelLog.superseded_by.is_not(None)).cte(
        "verified_lineage", recursive=True)
    descendant = aliased(LabelLog)
    lineage = lineage.union_all(select(
        lineage.c.root_id, descendant.superseded_by, lineage.c.tenant_id, lineage.c.domain_id,
    ).select_from(lineage).join(descendant, and_(
        descendant.tenant_id == lineage.c.tenant_id,
        descendant.domain_id == lineage.c.domain_id,
        descendant.label_id == lineage.c.next_id,
    )).where(descendant.superseded_by.is_not(None)))
    replacement = aliased(LabelLog)
    replacement_verified = exists(select(replacement.id).select_from(lineage).join(replacement, and_(
        replacement.tenant_id == lineage.c.tenant_id,
        replacement.domain_id == lineage.c.domain_id,
        replacement.label_id == lineage.c.next_id,
        replacement.verified_at.is_not(None),
    )).where(lineage.c.root_id == LabelLog.id))
    return or_(LabelLog.superseded_by.is_(None), ~replacement_verified)


async def verified_accuracy(session: AsyncSession, domain_id: str, category: str,
                            annotator_id: str | None = None) -> tuple[int, float | None]:
    """Return the verified count and fraction correct for this category and scope."""
    query = select(
        func.count(), func.avg(case((LabelLog.verified_outcome.is_(True), 1.0), else_=0.0))
    ).where(LabelLog.domain_id == domain_id, LabelLog.tenant_id == _tenant(session),
            LabelLog.category == category,
            LabelLog.verified_at.is_not(None), LabelLog.verified_outcome.is_not(None),
            active_verified_evidence(domain_id, _tenant(session)))
    if annotator_id is not None:
        query = query.where(LabelLog.annotator_id == annotator_id)
    count, accuracy = (await session.execute(query)).one()
    return count, float(accuracy) if accuracy is not None else None


async def get_label_log(session: AsyncSession, domain_id: str, category: str | None = None,
                        annotator_id: str | None = None, verified_only: bool = False,
                        limit: int = 50) -> list[LabelLog]:
    query = select(LabelLog).where(LabelLog.domain_id == domain_id,
                                    LabelLog.tenant_id == _tenant(session),
                                    LabelLog.superseded_by.is_(None))
    if category is not None:
        query = query.where(LabelLog.category == category)
    if annotator_id is not None:
        query = query.where(LabelLog.annotator_id == annotator_id)
    if verified_only:
        query = query.where(LabelLog.verified_at.is_not(None))
    if verified_only:
        query = query.order_by(LabelLog.verified_at.desc(), LabelLog.scored_at.desc(), LabelLog.id.desc())
    else:
        query = query.order_by(LabelLog.scored_at.desc(), LabelLog.id.desc())
    query = query.limit(limit)
    return list((await session.scalars(query)).all())


async def upsert_annotator(session: AsyncSession, domain_id: str, annotator_id: str) -> Annotator:
    dialect = session.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise ValueError(f"Unsupported database dialect: {dialect}")
    now = datetime.now(timezone.utc)
    values = {"domain_id": domain_id, "tenant_id": _tenant(session), "annotator_id": annotator_id,
              "label_count": 1, "last_active": now}
    changes = {"label_count": Annotator.label_count + 1, "last_active": now}
    statement: Insert
    if dialect == "postgresql":
        statement = pg_insert(Annotator).values(**values).on_conflict_do_update(
            constraint="uq_annotator_domain_external", set_=changes)
    else:
        statement = sqlite_insert(Annotator).values(**values).on_conflict_do_update(
            index_elements=[Annotator.domain_id, Annotator.annotator_id], set_=changes)
    await session.execute(statement)
    row = await get_annotator(session, domain_id, annotator_id)
    assert row is not None
    await session.refresh(row)
    return row


async def get_annotator(session: AsyncSession, domain_id: str, annotator_id: str) -> Annotator | None:
    return await session.scalar(select(Annotator).where(Annotator.domain_id == domain_id,
                                                       Annotator.tenant_id == _tenant(session),
                                                       Annotator.annotator_id == annotator_id))


# In PostgreSQL a scored label and its existing engine snapshot can be written
# together. The dependency on the insert retains label-before-engine ordering.
_scored_label = insert(LabelLog).values(
    domain_id=bindparam("p_domain"), tenant_id=bindparam("p_tenant"),
    label_id=bindparam("p_label"), annotator_id=bindparam("p_annotator"),
    category=bindparam("p_category"), factors_json=bindparam("p_factors"),
    recommended_action=bindparam("p_action"), confidence=bindparam("p_confidence"),
    text=bindparam("p_text"), notes=bindparam("p_notes"),
).returning(LabelLog.id).cte("scored_label")

_advanced_engine = update(Engine).where(
    Engine.domain_id == bindparam("p_domain"), Engine.tenant_id == bindparam("p_tenant"),
    Engine.annotator_id.is_not_distinct_from(bindparam("p_annotator")),
    Engine.version == bindparam("p_version"), exists(select(_scored_label.c.id)),
).values(state_json=bindparam("p_state"), version=Engine.version + 1,
         updated_at=bindparam("p_time")).returning(Engine.id, Engine.version).cte("advanced_engine")
_persist_existing_score = select(_advanced_engine.c.id, _advanced_engine.c.version)


async def score_and_persist(session: AsyncSession, engine: JudgmentMemoryEngine, domain_id: str,
                            label_id: str, annotator_id: str | None, category: str,
                            factors: dict[str, float], text: str | None = None,
                            notes: str | None = None) -> ScoreResult:
    result = engine.score(factors, category)
    expected = getattr(engine, "_db_version", 0)
    if expected and session.get_bind().dialect.name == "postgresql":
        await session.flush()
        state = engine.export_state()
        updated_at = datetime.now(timezone.utc)
        updated = (await session.execute(_persist_existing_score, {
            "p_domain": domain_id, "p_tenant": _tenant(session), "p_label": label_id,
            "p_annotator": annotator_id, "p_category": category, "p_factors": factors,
            "p_action": result.recommended_action, "p_confidence": result.confidence,
            "p_text": text, "p_notes": notes, "p_version": expected,
            "p_state": state, "p_time": updated_at,
        })).one_or_none()
        if updated is None:
            raise StaleDataError("Engine version changed during update")
        cached = session.identity_map.get(session.identity_key(Engine, updated.id))
        if cached is not None:
            set_committed_value(cached, "state_json", state)
            set_committed_value(cached, "version", updated.version)
            set_committed_value(cached, "updated_at", updated_at)
        setattr(engine, "_db_version", updated.version)
        return result
    await record_score(session, domain_id, label_id, annotator_id, category,
                       factors, result.recommended_action, result.confidence, text, notes)
    await save_engine_state(session, domain_id, annotator_id, engine)
    return result


async def verify_and_relearn(session: AsyncSession, domain_id: str, old_row: LabelLog,
                             actual_action: str, verified_outcome: bool,
                             annotator_id: str | None) -> LearnResult:
    """Retain the old judgment and append a verified revision in its own scope.

    Historical centroid movement remains in the original scope. The revision
    trains only the selected annotator engine and supersedes the old metric row.
    """
    if old_row.tenant_id != _tenant(session) or old_row.domain_id != domain_id:
        raise HTTPException(status_code=404, detail="Label not found")
    label_id = f"revision:{uuid4().hex}"
    assert old_row.category is not None
    engine = await load_or_create_engine(session, domain_id, annotator_id)
    domain = await get_domain(session, domain_id)
    if domain is None or old_row.category not in domain.config_json["categories"]:
        raise HTTPException(422, detail="Category not in domain schema")
    sync_engine_categories(engine, domain.config_json["categories"])
    scored = await score_and_persist(session, engine, domain_id, label_id, annotator_id,
                                     old_row.category, old_row.factors_json)
    result = await verify_and_learn(session, engine, domain_id, label_id,
                                    actual_action, verified_outcome)
    successor = await session.scalar(select(LabelLog).where(
        LabelLog.domain_id == domain_id, LabelLog.tenant_id == _tenant(session),
        LabelLog.label_id == label_id))
    assert successor is not None
    successor.annotation_id = old_row.annotation_id
    successor.source_task_id = old_row.source_task_id
    successor.text = old_row.text
    successor.notes = old_row.notes
    successor.review_notes = old_row.review_notes
    successor.prior_revision_id = str(old_row.id)
    successor.revision_actor = _tenant(session)
    successor.revision_by_key_id = session.info.get("actor_key_id") or session.info.get("payer_key_id")
    successor.revision_at = datetime.now(timezone.utc)
    await copy_label_content(session, old_row.id, successor.id)
    old_row.superseded_by = label_id
    await session.flush()
    return result


async def verify_and_learn(session: AsyncSession, engine: JudgmentMemoryEngine, domain_id: str,
                           label_id: str, actual_action: str, verified_outcome: bool,
                           reason: str | None = None, notes: str | None = None) -> LearnResult:
    row = await session.scalar(select(LabelLog).where(LabelLog.domain_id == domain_id,
                                                     LabelLog.tenant_id == _tenant(session),
                                                     LabelLog.label_id == label_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Label not found")
    if row.verified_at is not None:
        raise ValueError("Label already verified")
    if actual_action not in engine.config.actions:
        raise ValueError(f"Unknown action: {actual_action}")
    # Core exports omit decision_log. Rebuild the pending entry from the durable score row.
    decision_id = f"label:{row.id}"
    engine.decision_log[decision_id] = {
        "factors": row.factors_json,
        "factor_vec": [row.factors_json.get(name, 0.5) for name in engine.config.factors],
        "category": row.category,
        "recommended_action": row.recommended_action,
        "confidence": row.confidence,
    }
    result = engine.learn(decision_id, actual_action,
                          confirmed=row.recommended_action == actual_action,
                          outcome_correct=verified_outcome, track_outcome=True)
    del engine.decision_log[decision_id]
    await record_verification(session, domain_id, label_id, actual_action, verified_outcome, reason, notes)
    await save_engine_state(session, domain_id, row.annotator_id, engine)
    return result
