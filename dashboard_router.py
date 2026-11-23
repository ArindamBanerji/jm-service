"""Read-only dashboard projections for persisted labeling domains."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from itertools import groupby
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import Float, and_, case, cast, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from db import repository
from auth import Tenant, scoped_domain_id
from db.connection import get_db
from db.models import Domain, LabelLog
from jm_core import DomainConfig, JudgmentMemoryEngine
from labeling_router import _category_stats
from policy_engine import TierStatus, evaluate_domain
from rate_limit import limiter

router = APIRouter(prefix="/v1/dashboard", tags=["Dashboard"])
Session = Annotated[AsyncSession, Depends(get_db)]


async def require_domain(domain_id: str, session: Session, tenant: Tenant) -> Domain:
    domain = await repository.get_domain(session, scoped_domain_id(tenant, domain_id))
    if domain is None:
        raise HTTPException(404, detail="Domain not found")
    session.info["public_domain_id"] = domain_id
    return domain


DashboardDomain = Annotated[Domain, Depends(require_domain)]
verified = and_(LabelLog.verified_at.is_not(None), LabelLog.verified_outcome.is_not(None),
                LabelLog.superseded_by.is_(None))


class Inversion(BaseModel):
    trusted_factor: str
    actual_signal_factor: str
    interpretation: str


class CurveSample(BaseModel):
    verified_count: int
    accuracy: float
    timestamp: datetime


class Overview(BaseModel):
    domain_id: str
    overall_accuracy: float | None
    total_verified: int
    total_labels: int
    categories: list[TierStatus]
    inversion: Inversion | None
    compounding_curve: list[CurveSample]
    generated_at: datetime


class Correction(BaseModel):
    category: str
    recommended_action: str
    actual_action: str
    count: int


class CorrectionPattern(Correction):
    percentage_of_category: float = Field(description="Percent of all corrections within this category.")


class Corrections(BaseModel):
    domain_id: str
    total_corrections: int
    correction_rate: float | None
    patterns: list[CorrectionPattern]
    top_pattern: Correction | None


class AnnotatorProfile(BaseModel):
    annotator_id: str
    total_labels: int
    verified_count: int
    accuracy: float | None
    strongest_category: str | None
    weakest_category: str | None
    last_active: datetime


class Annotators(BaseModel):
    domain_id: str
    annotators: list[AnnotatorProfile]


class FactorStat(BaseModel):
    factor: str
    mean_correct: float | None
    mean_incorrect: float | None
    predictive_gap: float | None


class Factors(BaseModel):
    domain_id: str
    factor_names: list[str]
    inversion: Inversion | None
    factor_stats: list[FactorStat]


class DetailedPoint(BaseModel):
    index: int = Field(description="Zero-based index within the returned series.")
    verified_count: int
    running_accuracy: float
    timestamp: datetime


class Compounding(BaseModel):
    domain_id: str
    category: str | None
    points: list[DetailedPoint]
    baseline_accuracy: float | None = Field(description="Cumulative accuracy at the first completed window.")
    current_accuracy: float | None
    improvement: float | None = Field(description="Current minus baseline accuracy in percentage points.")


def _utc(value: datetime) -> datetime:
    # SQLite returns naive timestamps for stored UTC values.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _inversion(engine: JudgmentMemoryEngine | None) -> Inversion | None:
    signal = engine.signal_confidence_inversion() if engine is not None else None
    return Inversion.model_validate(signal) if signal else None


async def _curve(session: AsyncSession, domain_id: str, window: int,
                 category: str | None = None) -> list[CurveSample]:
    order = (LabelLog.verified_at, LabelLog.scored_at, LabelLog.id)
    history = select(
        LabelLog.verified_at.label("timestamp"),
        func.row_number().over(order_by=order).label("n"),
        func.count().over().label("total"),
        func.sum(case((LabelLog.verified_outcome.is_(True), 1), else_=0))
        .over(order_by=order, rows=(None, 0)).label("correct"),
    ).where(LabelLog.domain_id == domain_id, LabelLog.tenant_id == session.info.get("tenant_id", ""), verified)
    if category is not None:
        history = history.where(LabelLog.category == category)
    samples = history.subquery()
    c = samples.c
    query = select(c.n, c.correct, c.timestamp).where(
        (c.n % window == 0) | (c.n == c.total)
    ).order_by(c.n)
    return [CurveSample(verified_count=n, accuracy=correct / n, timestamp=_utc(timestamp))
            for n, correct, timestamp in await session.execute(query)]


@router.get("/{domain_id}/overview")
@limiter.limit("60/minute")
async def overview(request: Request, domain: DashboardDomain, session: Session) -> Overview:
    config = DomainConfig.from_dict(domain.config_json)
    engine = await repository.load_engine(session, domain.domain_id)
    if engine is None:
        engine = JudgmentMemoryEngine(config)
    # A stored project snapshot can predate categories added by an annotator engine.
    engine.config.categories = list(config.categories)
    stats = await _category_stats(session, domain.domain_id, config.categories)
    categories = evaluate_domain(engine, stats)
    curve = await _curve(session, domain.domain_id, 10)
    total = await session.scalar(select(func.count()).select_from(LabelLog)
                                 .where(LabelLog.domain_id == domain.domain_id,
                                        LabelLog.tenant_id == session.info.get("tenant_id", ""),
                                        LabelLog.superseded_by.is_(None)))
    return Overview(domain_id=session.info.get("public_domain_id", domain.domain_id), overall_accuracy=curve[-1].accuracy if curve else None,
                    total_verified=curve[-1].verified_count if curve else 0, total_labels=total or 0,
                    categories=list(categories.values()), inversion=_inversion(engine),
                    compounding_curve=curve, generated_at=datetime.now(timezone.utc))


@router.get("/{domain_id}/corrections")
@limiter.limit("60/minute")
async def corrections(request: Request, domain: DashboardDomain, session: Session) -> Corrections:
    count = func.count()
    groups = (LabelLog.category, LabelLog.recommended_action, LabelLog.actual_action)
    query = (select(*groups, count).where(LabelLog.domain_id == domain.domain_id, LabelLog.tenant_id == session.info.get("tenant_id", ""), verified)
             .group_by(*groups).order_by(count.desc(), *groups))
    total_verified = 0
    by_category: Counter[str] = Counter()
    overrides: list[Correction] = []
    for category, original, actual, n in await session.execute(query):
        total_verified += n
        if actual is not None and original != actual:
            by_category[category] += n
            overrides.append(Correction(category=category, recommended_action=original,
                                        actual_action=actual, count=n))
    patterns = [CorrectionPattern(**row.model_dump(), percentage_of_category=100 * row.count / by_category[row.category])
                for row in overrides]
    total = sum(by_category.values())
    return Corrections(domain_id=session.info.get("public_domain_id", domain.domain_id), total_corrections=total,
                       correction_rate=total / total_verified if total_verified else None,
                       patterns=patterns, top_pattern=overrides[0] if overrides else None)


@router.get("/{domain_id}/annotators")
@limiter.limit("60/minute")
async def annotators(request: Request, domain: DashboardDomain, session: Session,
                     limit: int = Query(50, ge=1, le=100)) -> Annotators:
    annotator = LabelLog.annotator_id
    total = func.count().label("total")
    top = (select(annotator, total).where(LabelLog.domain_id == domain.domain_id, LabelLog.tenant_id == session.info.get("tenant_id", ""),
                                         LabelLog.superseded_by.is_(None), annotator.is_not(None))
           .group_by(annotator).order_by(total.desc(), annotator).limit(limit).subquery())
    activity = case((LabelLog.verified_at > LabelLog.scored_at, LabelLog.verified_at), else_=LabelLog.scored_at)
    query = (select(annotator, top.c.total, LabelLog.category,
                    func.count(case((verified, 1))),
                    func.sum(case((and_(verified, LabelLog.verified_outcome.is_(True)), 1), else_=0)),
                    func.max(activity))
             .join(top, top.c.annotator_id == annotator).where(LabelLog.domain_id == domain.domain_id,
                 LabelLog.tenant_id == session.info.get("tenant_id", ""), LabelLog.superseded_by.is_(None))
             .group_by(annotator, top.c.total, LabelLog.category)
             .order_by(top.c.total.desc(), annotator, LabelLog.category))
    profiles: list[AnnotatorProfile] = []
    for name, rows in groupby(await session.execute(query), key=lambda row: row[0]):
        observed = correct = 0
        rates: dict[str, float] = {}
        group = list(rows)
        for _, _, category, n, hits, _ in group:
            observed += n
            correct += hits
            if n:
                rates[category] = hits / n
        profiles.append(AnnotatorProfile(
            annotator_id=name, total_labels=group[0][1], verified_count=observed,
            accuracy=correct / observed if observed else None,
            strongest_category=max(rates, key=rates.__getitem__) if rates else None,
            weakest_category=min(rates, key=rates.__getitem__) if rates else None,
            last_active=_utc(max(row[5] for row in group)),
        ))
    return Annotators(domain_id=session.info.get("public_domain_id", domain.domain_id), annotators=profiles)


@router.get("/{domain_id}/factors")
@limiter.limit("60/minute")
async def factors(request: Request, domain: DashboardDomain, session: Session) -> Factors:
    names = DomainConfig.from_dict(domain.config_json).factors
    engine = await repository.load_engine(session, domain.domain_id)
    # Expand JSON objects as key/value rows; custom factor names are literal keys.
    expand = func.json_each_text if session.get_bind().dialect.name == "postgresql" else func.json_each
    entries = expand(LabelLog.factors_json).table_valued("key", "value")
    query = (select(entries.c.key, LabelLog.verified_outcome, func.avg(cast(entries.c.value, Float)))
             .select_from(LabelLog).join(entries, true())
             .where(LabelLog.domain_id == domain.domain_id, LabelLog.tenant_id == session.info.get("tenant_id", ""), verified, entries.c.key.in_(names))
             .group_by(entries.c.key, LabelLog.verified_outcome))
    means = {(key, outcome): mean for key, outcome, mean in await session.execute(query)}

    results = []
    for name in names:
        positive = means.get((name, True))
        negative = means.get((name, False))
        gap = abs(positive - negative) if positive is not None and negative is not None else None
        results.append(FactorStat(factor=name, mean_correct=positive, mean_incorrect=negative, predictive_gap=gap))
    results.sort(key=lambda stat: stat.predictive_gap if stat.predictive_gap is not None else -1, reverse=True)
    return Factors(domain_id=session.info.get("public_domain_id", domain.domain_id), factor_names=names, inversion=_inversion(engine), factor_stats=results)


@router.get("/{domain_id}/compounding")
@limiter.limit("60/minute")
async def compounding(request: Request, domain: DashboardDomain, session: Session, window: int = Query(10, ge=1, le=2**31-1),
                      category: str | None = None) -> Compounding:
    curve = await _curve(session, domain.domain_id, window, category)
    baseline = curve[0].accuracy if curve and curve[0].verified_count >= window else None
    current = curve[-1].accuracy if curve else None
    points = [DetailedPoint(index=i, verified_count=p.verified_count, running_accuracy=p.accuracy, timestamp=p.timestamp)
              for i, p in enumerate(curve)]
    return Compounding(domain_id=session.info.get("public_domain_id", domain.domain_id), category=category, points=points,
                       baseline_accuracy=baseline, current_accuracy=current,
                       improvement=(current - baseline) * 100 if baseline is not None and current is not None else None)
