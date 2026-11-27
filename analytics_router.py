"""Project analytics projections over existing labels and predictions."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import load_only
from sqlalchemy.ext.asyncio import AsyncSession

from auth import ProjectTenant, selected_domain_id
from db import repository
from db.connection import get_db
from db.models import Domain, LabelLog, Prediction
from jm_core import DomainConfig
from rate_limit import limiter

router = APIRouter(prefix="/v1/projects/{domain_id}/analytics", tags=["Project analytics"])
Session = Annotated[AsyncSession, Depends(get_db)]


class DistributionCategory(BaseModel):
    name: str
    count: int
    pct: float
    verified: int
    pending: int


class DistributionResponse(BaseModel):
    categories: list[DistributionCategory]
    total: int
    imbalance_warning: str | None


class DailyThroughput(BaseModel):
    date: str
    labels: int
    verified: int
    avg_time_sec: float | None


class AnnotatorThroughput(BaseModel):
    id: str
    name: str
    labels_total: int
    labels_today: int
    avg_time_sec: float | None


class ThroughputSummary(BaseModel):
    total_labels: int
    avg_per_day: float
    avg_time_sec: float | None


class ThroughputResponse(BaseModel):
    daily: list[DailyThroughput]
    annotators: list[AnnotatorThroughput]
    summary: ThroughputSummary


class ConfusionResponse(BaseModel):
    categories: list[str]
    matrix: list[list[int]]
    top_confusions: list[dict[str, str | int | float]]


class LowestAgreement(BaseModel):
    a: str
    b: str
    agreement: float
    worst_category: str | None


class AgreementResponse(BaseModel):
    annotators: list[str]
    matrix: list[list[float]]
    per_category: dict[str, list[list[float]]]
    lowest_pair: LowestAgreement | None
    note: str | None = None


async def _project(session: AsyncSession, tenant: str, public_id: str) -> Domain:
    project = await repository.get_domain(session, selected_domain_id(session, tenant, public_id))
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _ordered_categories(project: Domain, observed: set[str]) -> list[str]:
    configured = DomainConfig.from_dict(project.config_json).categories
    return [*configured, *sorted(observed - set(configured))]


@router.get("/distribution", response_model=DistributionResponse)
@limiter.limit("60/minute")
async def distribution(request: Request, domain_id: str, tenant: ProjectTenant,
                       session: Session) -> DistributionResponse:
    project = await _project(session, tenant, domain_id)
    rows = await session.execute(select(LabelLog.category, func.count(), func.count(LabelLog.verified_at)).where(
        LabelLog.domain_id == project.domain_id, LabelLog.tenant_id == project.tenant_id,
        LabelLog.superseded_by.is_(None), LabelLog.category.is_not(None)).group_by(LabelLog.category))
    counts: Counter[str] = Counter()
    verified: Counter[str] = Counter()
    for category, count, reviewed in rows:
        if category is not None:
            counts[category] = count
            verified[category] = reviewed
    total = sum(counts.values())
    names = _ordered_categories(project, set(counts)) if total else []
    categories = [DistributionCategory(
        name=name, count=counts[name], pct=round(100 * counts[name] / total, 1),
        verified=verified[name], pending=counts[name] - verified[name],
    ) for name in sorted(names, key=lambda name: (-counts[name], name))]
    warning = None
    if categories:
        mean = total / len(categories)
        smallest = min(categories, key=lambda item: (item.count, item.name))
        if smallest.count < mean * .1:
            warning = (f"{smallest.name} has {smallest.pct:.1f}% of labels — "
                       "consider adding more examples")
    return DistributionResponse(categories=categories, total=total, imbalance_warning=warning)


@dataclass
class _Durations:
    total: float = 0
    count: int = 0

    def add(self, seconds: float) -> None:
        self.total += seconds
        self.count += 1

    def average(self) -> float | None:
        return round(self.total / self.count, 1) if self.count else None


@router.get("/throughput", response_model=ThroughputResponse)
@limiter.limit("60/minute")
async def throughput(request: Request, domain_id: str, tenant: ProjectTenant, session: Session,
                     days: int = Query(7, ge=1, le=90)) -> ThroughputResponse:
    project = await _project(session, tenant, domain_id)
    today = datetime.now(timezone.utc).date()
    first_day = today - timedelta(days=days - 1)
    rows = await session.stream(select(LabelLog.annotator_id, LabelLog.scored_at, LabelLog.verified_at).where(
        LabelLog.domain_id == project.domain_id, LabelLog.tenant_id == project.tenant_id,
        or_(LabelLog.scored_at.is_not(None), LabelLog.verified_at.is_not(None)))
        .order_by(LabelLog.annotator_id, LabelLog.scored_at, LabelLog.id).execution_options(yield_per=500))
    previous: dict[str, datetime] = {}
    annotator_times: dict[str, _Durations] = defaultdict(_Durations)
    daily_times: dict[date, _Durations] = defaultdict(_Durations)
    durations = _Durations()
    daily_labels: Counter[date] = Counter()
    daily_verified: Counter[date] = Counter()
    annotator_total: Counter[str] = Counter()
    annotator_today: Counter[str] = Counter()
    async for row in rows:
        if row.scored_at is not None:
            moment = _utc(row.scored_at)
            scored_day = moment.date()
            if first_day <= scored_day <= today:
                daily_labels[scored_day] += 1
            if row.annotator_id is not None:
                prior = previous.get(row.annotator_id)
                previous[row.annotator_id] = moment
                if prior is not None:
                    gap = (moment - prior).total_seconds()
                    if 0 < gap <= 300:
                        annotator_times[row.annotator_id].add(gap)
                        if first_day <= prior.date() <= scored_day <= today:
                            durations.add(gap)
                            daily_times[scored_day].add(gap)
                annotator_total[row.annotator_id] += 1
                if scored_day == today:
                    annotator_today[row.annotator_id] += 1
        if row.verified_at is not None:
            verified_day = _utc(row.verified_at).date()
            if first_day <= verified_day <= today:
                daily_verified[verified_day] += 1
    daily = [DailyThroughput(date=str(day), labels=daily_labels[day], verified=daily_verified[day],
                               avg_time_sec=daily_times[day].average())
             for day in (first_day + timedelta(days=offset) for offset in range(days))]
    annotators = [AnnotatorThroughput(id=name, name=name, labels_total=count,
                                      labels_today=annotator_today[name],
                                      avg_time_sec=annotator_times[name].average())
                  for name, count in sorted(annotator_total.items(), key=lambda item: (-item[1], item[0]))]
    period_total = sum(daily_labels.values())
    return ThroughputResponse(daily=daily, annotators=annotators,
        summary=ThroughputSummary(total_labels=period_total, avg_per_day=round(period_total / days, 1),
                                  avg_time_sec=durations.average()))


def _root_category(row: LabelLog, by_id: dict[str, LabelLog]) -> str | None:
    current = row
    visited: set[str] = set()
    while current.prior_revision_id and current.prior_revision_id not in visited:
        visited.add(current.prior_revision_id)
        predecessor = by_id.get(current.prior_revision_id)
        if predecessor is None:
            break
        current = predecessor
    return current.category


@router.get("/confusion", response_model=ConfusionResponse)
@limiter.limit("60/minute")
async def confusion(request: Request, domain_id: str, tenant: ProjectTenant, session: Session,
                    source: Literal["human", "prediction", "all"] = "all") -> ConfusionResponse:
    project = await _project(session, tenant, domain_id)
    labels = list((await session.scalars(select(LabelLog).options(load_only(
        LabelLog.prior_revision_id, LabelLog.superseded_by, LabelLog.category, LabelLog.verified_at)).where(
        LabelLog.domain_id == project.domain_id, LabelLog.tenant_id == project.tenant_id))).all())
    current = {row.id: row for row in labels if row.superseded_by is None}
    by_id = {str(row.id): row for row in labels}
    predictions = list((await session.scalars(select(Prediction).options(load_only(
        Prediction.current_label_log_id, Prediction.original_category, Prediction.human_reviewed_at)).where(
        Prediction.project_id == project.id))).all())
    prediction_by_label = {row.current_label_log_id: row for row in predictions}
    pairs: list[tuple[str, str]] = []
    if source in {"prediction", "all"}:
        for label_id, prediction in prediction_by_label.items():
            label = current.get(label_id)
            if label is not None and label.category is not None and prediction.human_reviewed_at is not None:
                pairs.append((prediction.original_category, label.category))
    if source in {"human", "all"}:
        for label_id, label in current.items():
            if label_id in prediction_by_label or label.category is None or label.verified_at is None:
                continue
            original = _root_category(label, by_id)
            if original is not None:
                pairs.append((original, label.category))
    observed = {category for pair in pairs for category in pair}
    categories = _ordered_categories(project, observed)
    index = {category: offset for offset, category in enumerate(categories)}
    matrix = [[0 for _ in categories] for _ in categories]
    for original, final in pairs:
        matrix[index[original]][index[final]] += 1
    top: list[dict[str, str | int | float]] = []
    for row_index, original in enumerate(categories):
        row_total = sum(matrix[row_index])
        for column_index, final in enumerate(categories):
            count = matrix[row_index][column_index]
            if row_index != column_index and count:
                top.append({"from": original, "to": final, "count": count,
                            "pct": round(100 * count / row_total, 1) if row_total else 0})
    top.sort(key=lambda pair: (-int(pair["count"]), str(pair["from"]), str(pair["to"])))
    return ConfusionResponse(categories=categories, matrix=matrix, top_confusions=top[:3])


def _agreement_matrix(annotators: list[str], observations: dict[str, dict[str, tuple[str, str]]],
                      category: str | None = None) -> list[list[float]]:
    matrix = [[0.0 for _ in annotators] for _ in annotators]
    for index in range(len(annotators)):
        matrix[index][index] = 1.0
    for left_index, right_index in combinations(range(len(annotators)), 2):
        left, right = annotators[left_index], annotators[right_index]
        shared = set(observations[left]) & set(observations[right])
        if category is not None:
            shared = {item for item in shared if category in {
                observations[left][item][0], observations[right][item][0]}}
        value = (sum(observations[left][item] == observations[right][item] for item in shared) / len(shared)
                 if shared else 0.0)
        matrix[left_index][right_index] = matrix[right_index][left_index] = round(value, 4)
    return matrix


@router.get("/agreement", response_model=AgreementResponse)
@limiter.limit("60/minute")
async def agreement(request: Request, domain_id: str, tenant: ProjectTenant,
                    session: Session) -> AgreementResponse:
    project = await _project(session, tenant, domain_id)
    rows = await session.stream(select(LabelLog.annotator_id, LabelLog.source_task_id,
        LabelLog.category, LabelLog.actual_action, LabelLog.recommended_action).where(
        LabelLog.domain_id == project.domain_id, LabelLog.tenant_id == project.tenant_id,
        LabelLog.superseded_by.is_(None), LabelLog.source_task_id.is_not(None),
        LabelLog.annotator_id.is_not(None), LabelLog.category.is_not(None))
        .order_by(LabelLog.scored_at, LabelLog.id).execution_options(yield_per=500))
    observations: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    async for row in rows:
        assert row.annotator_id is not None and row.source_task_id is not None and row.category is not None
        action = row.actual_action or row.recommended_action or ""
        observations[row.annotator_id][row.source_task_id] = (row.category, action)
    annotators = sorted(name for name in observations if any(
        set(observations[name]) & set(observations[other]) for other in observations if other != name))
    if len(annotators) < 2:
        return AgreementResponse(annotators=[], matrix=[], per_category={}, lowest_pair=None,
            note="Agreement requires at least 2 annotators with overlapping items.")
    matrix = _agreement_matrix(annotators, observations)
    categories = sorted({value[0] for name in annotators for value in observations[name].values()})
    per_category = {category: _agreement_matrix(annotators, observations, category) for category in categories}
    pair_values = [(matrix[a][b], a, b) for a, b in combinations(range(len(annotators)), 2)
                   if set(observations[annotators[a]]) & set(observations[annotators[b]])]
    lowest_value, left, right = min(pair_values)
    category_values = [(per_category[category][left][right], category) for category in categories
                       if any(category in {observations[annotators[left]][item][0],
                                           observations[annotators[right]][item][0]}
                              for item in set(observations[annotators[left]]) & set(observations[annotators[right]]))]
    worst = min(category_values)[1] if category_values else None
    return AgreementResponse(annotators=annotators, matrix=matrix, per_category=per_category,
        lowest_pair=LowestAgreement(a=annotators[left], b=annotators[right],
                                    agreement=lowest_value, worst_category=worst))
