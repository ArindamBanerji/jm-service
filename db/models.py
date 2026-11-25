"""SQLAlchemy tables for labeling state and verified labels."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, BigInteger, JSON, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (
        CheckConstraint("status IN ('active','archived','completed')", name="ck_domain_status"),
        CheckConstraint("confidence_floor BETWEEN 0.80 AND 0.99", name="ck_domain_confidence_floor"),
        CheckConstraint("settings_version >= 1", name="ck_domain_settings_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    domain_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    public_domain_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True, default="")
    domain_name: Mapped[str] = mapped_column(String(200))
    config_json: Mapped[dict] = mapped_column(JSON)
    guidelines: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    automation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    confidence_floor: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.95"))
    settings_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
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
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_key_owner"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(200), index=True)
    tenant_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tier: Mapped[str] = mapped_column(String(20), default="trial", nullable=False, server_default="trial")
    subscription_state: Mapped[str | None] = mapped_column(Enum("trial", "trial_expired", "active", "past_due", "paused", "cancelled", "cleaned_up", name="subscription_lifecycle"), nullable=True)
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    paddle_customer_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    paddle_subscription_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    paddle_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    paddle_event_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
Index("uq_api_keys_paddle_customer_id", ApiKey.paddle_customer_id, unique=True,
      postgresql_where=ApiKey.paddle_customer_id.is_not(None),
      sqlite_where=ApiKey.paddle_customer_id.is_not(None))


class TenantGuard(Base):
    __tablename__ = "tenant_guard"
    tenant_id: Mapped[str] = mapped_column(String(200), primary_key=True)


class ProjectBillingOwner(Base):
    __tablename__ = "project_billing_owner"
    __table_args__ = (ForeignKeyConstraint(
        ["owner_tenant_id", "billing_key_id"], ["api_keys.tenant_id", "api_keys.id"]),)
    owner_tenant_id: Mapped[str] = mapped_column(String(200), ForeignKey("tenant_guard.tenant_id"), primary_key=True)
    billing_key_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), unique=True, nullable=False)
    trial_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CheckoutIntent(Base):
    __tablename__ = "checkout_intent"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "purchaser"], ["api_keys.tenant_id", "api_keys.id"]),
        ForeignKeyConstraint(["tenant_id", "payer"], ["api_keys.tenant_id", "api_keys.id"]),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False)
    purchaser: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    payer: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    transaction_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SubscriptionBinding(Base):
    __tablename__ = "subscription_binding"
    subscription_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    payer: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("api_keys.id"), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("one_current_sub", SubscriptionBinding.payer, unique=True,
      postgresql_where=SubscriptionBinding.retired_at.is_(None),
      sqlite_where=SubscriptionBinding.retired_at.is_(None))


class TransitionLog(Base):
    __tablename__ = "transition_log"
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    key_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("api_keys.id"))
    subscription_id: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(String(200))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    old_state: Mapped[str | None] = mapped_column(Enum("trial", "trial_expired", "active", "past_due", "paused", "cancelled", "cleaned_up", name="subscription_lifecycle"))
    new_state: Mapped[str | None] = mapped_column(Enum("trial", "trial_expired", "active", "past_due", "paused", "cancelled", "cleaned_up", name="subscription_lifecycle"))
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    key_version: Mapped[int | None] = mapped_column(BigInteger)


class LifecycleNotice(Base):
    __tablename__ = "lifecycle_notice"
    event_id: Mapped[str] = mapped_column(String(200), ForeignKey("transition_log.event_id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignupChallenge(Base):
    __tablename__ = "signup_challenge"
    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    requested_name: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectMember(Base):
    __tablename__ = "project_member"
    __table_args__ = (
        UniqueConstraint("project_id", "member_tenant_id", name="uq_project_member_tenant"),
        CheckConstraint("role IN ('admin','reviewer','annotator')", name="ck_project_member_role"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    member_tenant_id: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    granted_by_key_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("api_keys.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectInvite(Base):
    __tablename__ = "project_invite"
    __table_args__ = (CheckConstraint("role IN ('admin','reviewer','annotator')", name="ck_project_invite_role"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    issued_by_key_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("api_keys.id"), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_key_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("api_keys.id"))
    accepted_member_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("project_member.id"))
    mail_status: Mapped[str] = mapped_column(String(16), nullable=False)
    last_mail_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("uq_open_project_invite", ProjectInvite.project_id, ProjectInvite.email, unique=True,
      postgresql_where=ProjectInvite.consumed_at.is_(None) & ProjectInvite.revoked_at.is_(None),
      sqlite_where=ProjectInvite.consumed_at.is_(None) & ProjectInvite.revoked_at.is_(None))


class PaddleWebhookEvent(Base):
    """Durable receipt committed in the same transaction as the entitlement."""
    __tablename__ = "paddle_webhook_events"
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
