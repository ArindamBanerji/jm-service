"""SQLAlchemy tables for labeling state and verified labels."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    domain_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    public_domain_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True, default="")
    domain_name: Mapped[str] = mapped_column(String(200))
    config_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Engine(Base):
    __tablename__ = "engines"
    __table_args__ = (
        UniqueConstraint("domain_id", "annotator_id", name="uq_engine_domain_annotator"),
        Index("uq_engine_project", "domain_id", unique=True,
              postgresql_where=text("annotator_id IS NULL"), sqlite_where=text("annotator_id IS NULL")),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    domain_id: Mapped[str] = mapped_column(ForeignKey("domains.domain_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True, default="")
    annotator_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    state_json: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LabelLog(Base):
    __tablename__ = "label_log"
    __table_args__ = (
        Index("ix_label_log_domain_category_verified", "domain_id", "category", "verified_at"),
        UniqueConstraint("domain_id", "label_id", name="uq_label_log_domain_label"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    domain_id: Mapped[str] = mapped_column(ForeignKey("domains.domain_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True, default="")
    superseded_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    label_id: Mapped[str] = mapped_column(String(200))
    annotation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_task_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    annotator_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), index=True, nullable=True)
    factors_json: Mapped[dict] = mapped_column(JSON)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actual_action: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verified_outcome: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    prior_revision_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    revision_actor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    revision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_token: Mapped[str | None] = mapped_column(String(200), nullable=True)


class LabelContent(Base):
    __tablename__ = "label_content"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True,
                                     default=uuid4, server_default=text("gen_random_uuid()"))
    label_log_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("label_log.id", ondelete="CASCADE"),
        unique=True, nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    spans_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class Annotator(Base):
    __tablename__ = "annotators"
    __table_args__ = (UniqueConstraint("domain_id", "annotator_id", name="uq_annotator_domain_external"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    domain_id: Mapped[str] = mapped_column(ForeignKey("domains.domain_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True, default="")
    annotator_id: Mapped[str] = mapped_column(String(200))
    label_count: Mapped[int] = mapped_column(Integer, default=0)
    last_active: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(200), index=True)
    tenant_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tier: Mapped[str] = mapped_column(String(20), default="trial", nullable=False, server_default="trial")
    paddle_customer_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    paddle_subscription_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    trial_expiring_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_expired_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    labels_this_month: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default=text("0"))
    labels_month_key: Mapped[str] = mapped_column(String(7), default="", nullable=False, server_default=text("''"))
    labels_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default=text("0"))
    labels_day_key: Mapped[str] = mapped_column(String(10), default="", nullable=False, server_default=text("''"))


Index("uq_api_keys_contact_email", func.lower(ApiKey.contact_email), unique=True,
      postgresql_where=ApiKey.contact_email.is_not(None),
      sqlite_where=ApiKey.contact_email.is_not(None))
