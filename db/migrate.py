"""Run `python jm-service/db/migrate.py` from the parent claude_projects directory."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from sqlalchemy import Connection, DateTime, Table, inspect, select, text
from sqlalchemy.orm import Session
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.connection import engine, sanitize_database_error
from db.models import (ApiKey, Base, CheckoutIntent, LabelContent, ProjectBillingOwner,
                       ProviderRepairManifest, ProviderRepairQuarantine,
                       SubscriptionBinding, TransitionLog)


def _upgrade_timestamps(connection: Connection, table: str, columns: tuple[str, ...]) -> None:
    postgres = connection.dialect.name == "postgresql"
    timestamp = "TIMESTAMPTZ" if postgres else "TIMESTAMP"
    existing = {col["name"]: col["type"] for col in inspect(connection).get_columns(table)}
    for column in columns:
        column_type = existing.get(column)
        if column_type is None:
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {timestamp}")
        elif postgres and isinstance(column_type, DateTime) and not column_type.timezone:
            # Earlier versions wrote naive UTC. A session-local cast can shift those instants.
            connection.exec_driver_sql(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TIMESTAMPTZ "
                f"USING {column} AT TIME ZONE 'UTC'")


def _rebuild_sqlite_label_log(connection: Connection) -> None:
    # SQLite's legacy driver can run DDL before beginning a transaction.
    # A savepoint keeps the replacement, child restore and indexes atomic.
    with connection.begin_nested():
        connection.execute(text("""CREATE TABLE label_log_new (
            id CHAR(32) PRIMARY KEY, domain_id VARCHAR(200) NOT NULL REFERENCES domains(domain_id),
            tenant_id VARCHAR(200) NOT NULL DEFAULT '', superseded_by VARCHAR(200),
            label_id VARCHAR(200) NOT NULL, annotation_id VARCHAR(200), source_task_id VARCHAR(200),
            source_updated_at TIMESTAMP,
            annotator_id VARCHAR(200), category VARCHAR(200), factors_json JSON NOT NULL,
            text TEXT, recommended_action VARCHAR(200), actual_action VARCHAR(200),
            verified_outcome BOOLEAN, confidence FLOAT, scored_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            verified_at DATETIME, verification_reason VARCHAR(1000),
            prior_revision_id VARCHAR(200), revision_actor VARCHAR(200),
            revision_at TIMESTAMP, idempotency_token VARCHAR(200),
            CONSTRAINT uq_label_log_domain_label UNIQUE (domain_id, label_id))"""))
        columns = ("id domain_id tenant_id superseded_by label_id annotation_id source_task_id source_updated_at "
                   "annotator_id category factors_json text recommended_action actual_action "
                   "verified_outcome confidence scored_at verified_at verification_reason prior_revision_id "
                   "revision_actor revision_at idempotency_token").split()
        selected = ", ".join(columns)
        connection.execute(text(
            f"INSERT INTO label_log_new ({selected}) SELECT {selected} FROM label_log"))
        has_content = inspect(connection).has_table("label_content")
        if has_content:
            connection.exec_driver_sql(
                "CREATE TEMP TABLE saved_label_content AS SELECT * FROM label_content")
            expected = connection.exec_driver_sql("SELECT count(*) FROM temp.saved_label_content").scalar_one()
            connection.exec_driver_sql("DELETE FROM label_content")
        connection.execute(text("DROP TABLE label_log"))
        connection.execute(text("ALTER TABLE label_log_new RENAME TO label_log"))
        if has_content:
            connection.exec_driver_sql("INSERT INTO label_content SELECT * FROM temp.saved_label_content")
            actual = connection.exec_driver_sql("SELECT count(*) FROM label_content").scalar_one()
            if actual != expected:
                raise RuntimeError(f"Label content count changed during rebuild: {expected} to {actual}")
            connection.exec_driver_sql("DROP TABLE temp.saved_label_content")
        for statement in (
            "CREATE INDEX ix_label_log_domain_id ON label_log (domain_id)",
            "CREATE INDEX ix_label_log_category ON label_log (category)",
            "CREATE INDEX ix_label_log_domain_category_verified ON label_log (domain_id, category, verified_at)",
        ):
            connection.execute(text(statement))


def repair_provider_links(connection: Connection) -> None:
    """Bind only confirmed Paddle IDs to an established, unambiguous payer."""
    if not inspect(connection).has_table("api_keys"):
        return
    now = datetime.now(timezone.utc)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        legacy_columns = {column["name"] for column in inspect(connection).get_columns("api_keys")}
        legacy_ids: set[UUID] = set()
        for column in ("lemon_squeezy_customer_id", "lemon_squeezy_subscription_id"):
            if column in legacy_columns:
                legacy_ids.update(UUID(str(value)) for value in session.scalars(text(
                    f"SELECT id FROM api_keys WHERE {column} IS NOT NULL")))
        candidates = list(session.scalars(select(ApiKey).where(
            (ApiKey.paddle_customer_id.is_not(None)) |
            (ApiKey.paddle_subscription_id.is_not(None)))).all())
        known = {key.id for key in candidates}
        candidates.extend(key for key in session.scalars(select(ApiKey).where(ApiKey.id.in_(legacy_ids)))
                          if key.id not in known)
        for key in candidates:
            if session.get(ProviderRepairManifest, key.id) is not None:
                continue
            if session.get(ProviderRepairQuarantine, key.id) is not None:
                continue
            customer, subscription = key.paddle_customer_id, key.paddle_subscription_id
            siblings = session.scalars(select(ApiKey).where(ApiKey.tenant_id == key.tenant_id)).all()
            owner = session.get(ProjectBillingOwner, key.tenant_id)
            binding = session.get(SubscriptionBinding, subscription) if subscription else None
            reason = None
            if key.id in legacy_ids:
                reason = "legacy_provider_conflict" if customer or subscription else "legacy_provider_unmapped"
            elif not customer or not customer.startswith("ctm_") or not subscription or not subscription.startswith("sub_"):
                reason = "unconfirmed_provider_ids"
            elif owner is None and len(siblings) != 1:
                reason = "ambiguous_payer"
            elif owner is not None and owner.billing_key_id != key.id:
                reason = "owner_mismatch"
            elif binding is not None and (binding.payer != key.id or binding.customer_id != customer):
                reason = "binding_mismatch"
            elif owner is not None and owner.trial_started_at.replace(tzinfo=timezone.utc) != key.created_at.replace(tzinfo=timezone.utc):
                reason = "trial_start_mismatch"
            if reason is not None:
                session.add(ProviderRepairQuarantine(
                    key_id=key.id, tenant_id=key.tenant_id,
                    reason_code=reason, quarantined_at=now))
                continue
            assert customer is not None and subscription is not None
            owner_created = owner is None
            binding_created = binding is None
            if owner_created:
                session.execute(text(
                    "INSERT INTO tenant_guard (tenant_id) VALUES (:tenant) ON CONFLICT DO NOTHING"),
                    {"tenant": key.tenant_id})
                session.add(ProjectBillingOwner(owner_tenant_id=key.tenant_id,
                                                billing_key_id=key.id,
                                                trial_started_at=key.created_at))
                session.flush()
            if binding_created:
                session.add(SubscriptionBinding(subscription_id=subscription,
                                                payer=key.id, customer_id=customer))
            session.add(ProviderRepairManifest(
                key_id=key.id, tenant_id=key.tenant_id, customer_id=customer,
                subscription_id=subscription, state_version=key.state_version,
                trial_started_at=key.created_at, labels_day_key=key.labels_day_key,
                labels_today=key.labels_today, labels_month_key=key.labels_month_key,
                labels_this_month=key.labels_this_month,
                owner_created=owner_created, binding_created=binding_created,
                repaired_at=now))
        session.commit()


def undo_provider_link(connection: Connection, key_id: UUID) -> bool:
    """Undo only an unchanged repair mapping; never remove live billing history."""
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        manifest = session.get(ProviderRepairManifest, key_id)
        if manifest is None:
            return False
        key = session.get(ApiKey, key_id)
        owner = session.get(ProjectBillingOwner, manifest.tenant_id)
        binding = session.get(SubscriptionBinding, manifest.subscription_id)
        if (key is None or owner is None or binding is None or
                owner.billing_key_id != key_id or binding.payer != key_id or
                binding.customer_id != manifest.customer_id or
                key.paddle_customer_id != manifest.customer_id or
                key.paddle_subscription_id != manifest.subscription_id or
                key.state_version != manifest.state_version or
                key.created_at.replace(tzinfo=timezone.utc) != manifest.trial_started_at.replace(tzinfo=timezone.utc) or
                (key.labels_day_key, key.labels_today, key.labels_month_key, key.labels_this_month) !=
                (manifest.labels_day_key, manifest.labels_today,
                 manifest.labels_month_key, manifest.labels_this_month)):
            raise ValueError("Provider repair has changed; manual reconciliation required")
        if session.scalar(select(CheckoutIntent.id).where(CheckoutIntent.tenant_id == manifest.tenant_id).limit(1)):
            raise ValueError("Provider repair has checkout history; manual reconciliation required")
        if session.scalar(select(TransitionLog.event_id).where(TransitionLog.key_id == key_id).limit(1)):
            raise ValueError("Provider repair has billing transitions; manual reconciliation required")
        if manifest.binding_created:
            session.delete(binding)
        if manifest.owner_created:
            session.delete(owner)
        session.delete(manifest)
        session.commit()
        return True


async def migrate() -> None:
    try:
        async with engine.begin() as connection:
            def upgrade(sync_connection: Connection) -> None:
                inspector = inspect(sync_connection)
                for table in ("domains", "engines", "label_log", "annotators"):
                    if not inspector.has_table(table):
                        continue
                    names = {column["name"] for column in inspector.get_columns(table)}
                    if "tenant_id" not in names:
                        sync_connection.execute(text(
                            f"ALTER TABLE {table} ADD COLUMN tenant_id VARCHAR(200) NOT NULL DEFAULT ''"))
                    if table == "domains" and "public_domain_id" not in names:
                        sync_connection.execute(text(
                            "ALTER TABLE domains ADD COLUMN public_domain_id VARCHAR(200)"))
                    if table == "domains" and "guidelines" not in names:
                        sync_connection.execute(text("ALTER TABLE domains ADD COLUMN guidelines TEXT"))
                    if table == "domains":
                        for column, definition in {
                            "description": "TEXT",
                            "status": "VARCHAR(16) NOT NULL DEFAULT 'active'",
                            "automation_enabled": "BOOLEAN NOT NULL DEFAULT false",
                            "confidence_floor": "FLOAT NOT NULL DEFAULT 0.95",
                            "settings_version": "INTEGER NOT NULL DEFAULT 1",
                        }.items():
                            if column not in names:
                                sync_connection.execute(text(f"ALTER TABLE domains ADD COLUMN {column} {definition}"))
                    if table == "label_log" and "superseded_by" not in names:
                        sync_connection.execute(text(
                            "ALTER TABLE label_log ADD COLUMN superseded_by VARCHAR(200)"))
                    if table == "label_log":
                        for column in ("annotation_id", "source_task_id"):
                            if column not in names:
                                sync_connection.execute(text(
                                    f"ALTER TABLE label_log ADD COLUMN {column} VARCHAR(200)"))
                        if "text" not in names:
                            sync_connection.execute(text("ALTER TABLE label_log ADD COLUMN text TEXT"))
                        for column, definition in {
                            "prior_revision_id": "VARCHAR(200)", "revision_actor": "VARCHAR(200)",
                            "idempotency_token": "VARCHAR(200)",
                            "verification_reason": "VARCHAR(1000)",
                        }.items():
                            if column not in names:
                                sync_connection.execute(text(f"ALTER TABLE label_log ADD COLUMN {column} {definition}"))
                        _upgrade_timestamps(sync_connection, table, ("revision_at", "source_updated_at"))
                        if sync_connection.dialect.name == "postgresql":
                            for column in ("category", "recommended_action", "confidence", "scored_at"):
                                sync_connection.execute(text(f"ALTER TABLE label_log ALTER COLUMN {column} DROP NOT NULL"))
                        elif any(column["name"] in {"category", "recommended_action", "confidence", "scored_at"}
                                 and not column["nullable"] for column in inspector.get_columns("label_log")):
                            _rebuild_sqlite_label_log(sync_connection)
                    sync_connection.execute(text(
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)"))
                if inspector.has_table("api_keys"):
                    names = {column["name"] for column in inspector.get_columns("api_keys")}
                    if sync_connection.dialect.name == "postgresql":
                        sync_connection.execute(text("""DO $$ BEGIN
                            CREATE TYPE subscription_lifecycle AS ENUM
                            ('trial','trial_expired','active','past_due','paused','cancelled','cleaned_up');
                            EXCEPTION WHEN duplicate_object THEN NULL; END $$"""))
                        state_type = "subscription_lifecycle"
                    else:
                        state_type = "VARCHAR(13)"
                    if "subscription_state" not in names:
                        sync_connection.execute(text(
                            f"ALTER TABLE api_keys ADD COLUMN subscription_state {state_type}"))
                    if "state_version" not in names:
                        sync_connection.execute(text(
                            "ALTER TABLE api_keys ADD COLUMN state_version BIGINT NOT NULL DEFAULT 0"))
                    sync_connection.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_key_owner ON api_keys (tenant_id, id)"))
                    additions = {
                        "tier": "VARCHAR(20) NOT NULL DEFAULT 'trial'",
                        "paddle_customer_id": "VARCHAR(200)",
                        "paddle_subscription_id": "VARCHAR(200)",
                        "paddle_event_id": "VARCHAR(200)",
                        "contact_email": "VARCHAR(200)",
                        "labels_this_month": "INTEGER NOT NULL DEFAULT 0",
                        "labels_month_key": "VARCHAR(7) NOT NULL DEFAULT ''",
                        "labels_today": "INTEGER NOT NULL DEFAULT 0",
                        "labels_day_key": "VARCHAR(10) NOT NULL DEFAULT ''",
                    }
                    _upgrade_timestamps(sync_connection, "api_keys", (
                        "trial_expiring_email_sent_at", "trial_expired_email_sent_at",
                        "cancelled_at", "paddle_event_occurred_at"))
                    for column, definition in additions.items():
                        if column not in names:
                            sync_connection.execute(text(
                                f"ALTER TABLE api_keys ADD COLUMN {column} {definition}"))
                    sync_connection.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_contact_email "
                        "ON api_keys (lower(contact_email)) WHERE contact_email IS NOT NULL"))
                    sync_connection.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_paddle_customer_id "
                        "ON api_keys (paddle_customer_id) WHERE paddle_customer_id IS NOT NULL"))
            await connection.run_sync(upgrade)
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(repair_provider_links)
            await connection.run_sync(lambda sync_connection:
                                      cast(Table, LabelContent.__table__).create(sync_connection, checkfirst=True))
    except Exception as exc:
        raise RuntimeError(f"Migration failed: {sanitize_database_error(exc)}") from None
    finally:
        try:
            await engine.dispose()
        except Exception as exc:
            raise RuntimeError(f"Migration cleanup failed: {sanitize_database_error(exc)}") from None


def run_migration() -> None:
    asyncio.run(migrate())


if __name__ == "__main__":
    run_migration()
