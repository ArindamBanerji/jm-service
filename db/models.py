"""SQLAlchemy tables for labeling state and verified labels."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CHAR, CheckConstraint, DateTime, Enum, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, BigInteger, JSON, LargeBinary, SmallInteger, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (
        CheckConstraint("status IN ('active','archived','completed')", name="ck_domain_status"),
        CheckConstraint("confidence_floor BETWEEN 0.80 AND 0.99", name="ck_domain_confidence_floor"),
        CheckConstraint("settings_version >= 1", name="ck_domain_settings_version"),
        CheckConstraint(
            "(content_type='text' AND label_schema IN ('single','multi','ner')) OR "
            "(content_type='image' AND label_schema IN ('single','multi'))",
            name="ck_domains_modality_pair"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    domain_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    public_domain_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True, default="")
    domain_name: Mapped[str] = mapped_column(String(200))
    config_json: Mapped[dict] = mapped_column(JSON)
    guidelines: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidelines_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    automation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    confidence_floor: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.95"))
    settings_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    content_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="text", server_default="text")
    label_schema: Mapped[str] = mapped_column(
        String(20), nullable=False, default="single", server_default="single")
    modality_enforced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"))
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
        Index("uq_revision_predecessor", "domain_id", "prior_revision_id", unique=True,
              postgresql_where=text("prior_revision_id IS NOT NULL"),
              sqlite_where=text("prior_revision_id IS NOT NULL")),
        UniqueConstraint("domain_id", "label_id", name="uq_label_log_domain_label"),
        CheckConstraint("recommended_action IS NULL OR length(recommended_action) <= 200",
                        name="ck_label_log_recommended_action_length"),
        CheckConstraint("actual_action IS NULL OR length(actual_action) <= 200",
                        name="ck_label_log_actual_action_length"),
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
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actual_action: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verified_outcome: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_key_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("api_keys.id"), nullable=True)
    verification_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    prior_revision_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    revision_actor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    revision_by_key_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("api_keys.id"), nullable=True)
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
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConnectorConfigRow(Base):
    __tablename__ = "connector_config"

    tenant_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))


class ProjectRequest(Base):
    __tablename__ = "project_request"

    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("domains.id"), primary_key=True)
    actor_key_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("api_keys.id"), primary_key=True)
    operation: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    payload_digest: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectExportSlot(Base):
    __tablename__ = "project_export_slot"
    __table_args__ = (CheckConstraint("slot IN (1,2)", name="ck_project_export_slot_number"),)

    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True)
    slot: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Prediction(Base):
    __tablename__ = "prediction"
    __table_args__ = (
        CheckConstraint("model_confidence BETWEEN 0 AND 1", name="ck_prediction_model_confidence"),
        CheckConstraint("state IN ('pending','auto_approved','human_reviewed')", name="ck_prediction_state"),
        CheckConstraint("assessment IS NULL OR assessment IN ('correct','incorrect','unknown')",
                        name="ck_prediction_assessment"),
        Index("ix_prediction_scope", "project_id", "source", "imported_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True,
                                     default=uuid4, server_default=text("gen_random_uuid()"))
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("domains.id"), nullable=False)
    original_label_log_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("label_log.id"), nullable=False, unique=True)
    current_label_log_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("label_log.id"), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[str] = mapped_column(String(200), nullable=False)
    original_content: Mapped[dict] = mapped_column(JSON, nullable=False)
    original_category: Mapped[str] = mapped_column(String(200), nullable=False)
    model_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    dlj_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    recommendation: Mapped[str] = mapped_column(String(200), nullable=False)
    gate_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    decision_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    machine_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    human_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_key_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("api_keys.id"), nullable=True)
    assessment: Mapped[str | None] = mapped_column(String(12), nullable=True)
    human_spans_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class WebhookEvent(Base):
    __tablename__ = "webhook_event"
    __table_args__ = (UniqueConstraint("project_id", "event_type", "transition_key",
                                       name="uq_webhook_event_transition"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True,
                                     default=uuid4, server_default=text("gen_random_uuid()"))
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    transition_key: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoint"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True,
                                     default=uuid4, server_default=text("gen_random_uuid()"))
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    subscribed_events: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    destination_version: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WebhookDelivery(Base):
    __tablename__ = "webhook_delivery"
    __table_args__ = (
        UniqueConstraint("endpoint_id", "event_id", name="uq_webhook_delivery_endpoint_event"),
        CheckConstraint(
            "state IN ('pending','leased','delivered','dead','cancelled')",
            name="ck_webhook_delivery_state"),
        Index("ix_delivery_due", "state", "next_attempt_at"),
        Index("ix_delivery_lease", "state", "lease_until"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True,
                                     default=uuid4, server_default=text("gen_random_uuid()"))
    endpoint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("webhook_endpoint.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("webhook_event.id", ondelete="CASCADE"), nullable=False)
    destination_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(100), nullable=True)


class WebhookAttempt(Base):
    __tablename__ = "webhook_attempt"

    delivery_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("webhook_delivery.id", ondelete="CASCADE"), primary_key=True)
    attempt_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
    signup_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signup_reconciliation_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reproof_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
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
Index("uq_api_keys_signup_email", func.lower(ApiKey.signup_email), unique=True,
      postgresql_where=ApiKey.signup_email.is_not(None),
      sqlite_where=ApiKey.signup_email.is_not(None))
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


class ProviderRepairManifest(Base):
    __tablename__ = "provider_repair_manifest"
    key_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("api_keys.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    subscription_id: Mapped[str] = mapped_column(String(200), nullable=False)
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trial_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    labels_day_key: Mapped[str] = mapped_column(String(10), nullable=False)
    labels_today: Mapped[int] = mapped_column(Integer, nullable=False)
    labels_month_key: Mapped[str] = mapped_column(String(7), nullable=False)
    labels_this_month: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_created: Mapped[bool] = mapped_column(Boolean, nullable=False)
    binding_created: Mapped[bool] = mapped_column(Boolean, nullable=False)
    repaired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderRepairQuarantine(Base):
    __tablename__ = "provider_repair_quarantine"
    key_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("api_keys.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    quarantined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
