"""Transactional labeling repository. Callers commit or roll back the session."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.sql.dml import Insert

from jm_core import DomainConfig, JudgmentMemoryEngine, LearnResult, ScoreResult
from db.models import Annotator, Domain, Engine, LabelLog


def _tenant(session: AsyncSession) -> str:
    return str(session.info.get("tenant_id", ""))


async def create_domain(session: AsyncSession, domain_id: str, domain_name: str,
                        config: DomainConfig, tenant_id: str | None = None) -> Domain:
    domain = Domain(domain_id=domain_id, tenant_id=tenant_id if tenant_id is not None else _tenant(session),
                    domain_name=domain_name, config_json=config.to_dict())
    session.add(domain)
    await session.flush()
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
    existing = await session.scalar(_engine_query(domain_id, annotator_id, _tenant(session)).with_for_update())
    if existing is None:
        row = Engine(domain_id=domain_id, tenant_id=_tenant(session), annotator_id=annotator_id,
                     state_json=state, version=1)
        session.add(row)
        await session.flush()
    else:
        expected = getattr(engine, "_db_version", 0)
        result = await session.execute(
            update(Engine).where(Engine.id == existing.id, Engine.tenant_id == _tenant(session),
                                 Engine.version == expected)
            .values(state_json=state, version=expected + 1, updated_at=datetime.now(timezone.utc))
        )
        if getattr(result, "rowcount", None) != 1:
            raise StaleDataError("Engine version changed during update")
        await session.refresh(existing)
        row = existing
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
    domain = await get_domain(session, domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return JudgmentMemoryEngine(DomainConfig.from_dict(domain.config_json))


async def record_score(session: AsyncSession, domain_id: str, label_id: str,
                       annotator_id: str | None, category: str, factors: dict[str, float],
                       recommended_action: str, confidence: float) -> LabelLog:
    row = LabelLog(domain_id=domain_id, tenant_id=_tenant(session), label_id=label_id, annotator_id=annotator_id,
                   category=category, factors_json=factors, recommended_action=recommended_action,
                   confidence=confidence)
    session.add(row)
    await session.flush()
    return row


async def record_verification(session: AsyncSession, domain_id: str, label_id: str,
                              actual_action: str, verified_outcome: bool) -> LabelLog:
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
    await session.flush()
    return row


async def verified_accuracy(session: AsyncSession, domain_id: str, category: str,
                            annotator_id: str | None = None) -> tuple[int, float | None]:
    """Return the verified count and fraction correct for this category and scope."""
    query = select(
        func.count(), func.avg(case((LabelLog.verified_outcome.is_(True), 1.0), else_=0.0))
    ).where(LabelLog.domain_id == domain_id, LabelLog.tenant_id == _tenant(session),
            LabelLog.category == category,
            LabelLog.verified_at.is_not(None), LabelLog.verified_outcome.is_not(None),
            LabelLog.superseded_by.is_(None))
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


async def score_and_persist(session: AsyncSession, engine: JudgmentMemoryEngine, domain_id: str,
                            label_id: str, annotator_id: str | None, category: str,
                            factors: dict[str, float]) -> ScoreResult:
    result = engine.score(factors, category)
    await record_score(session, domain_id, label_id, annotator_id, category,
                       factors, result.recommended_action, result.confidence)
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
    engine = await load_or_create_engine(session, domain_id, annotator_id)
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
    old_row.superseded_by = label_id
    await session.flush()
    return result


async def verify_and_learn(session: AsyncSession, engine: JudgmentMemoryEngine, domain_id: str,
                           label_id: str, actual_action: str, verified_outcome: bool) -> LearnResult:
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
    await record_verification(session, domain_id, label_id, actual_action, verified_outcome)
    await save_engine_state(session, domain_id, row.annotator_id, engine)
    return result
