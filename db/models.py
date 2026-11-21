"""SQLAlchemy tables for labeling state and verified labels."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    domain_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
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
    category: Mapped[str] = mapped_column(String(200), index=True)
    factors_json: Mapped[dict] = mapped_column(JSON)
    recommended_action: Mapped[str] = mapped_column(String(200))
    actual_action: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verified_outcome: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
