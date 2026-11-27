"""Run `python jm-service/db/migrate.py` from the parent claude_projects directory."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from sqlalchemy import Connection, DateTime, String, Table, inspect, select, text
from sqlalchemy.orm import Session
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.connection import engine, sanitize_database_error
from db.entitlement import entitlement_decision
from db.models import (ApiKey, Base, CheckoutIntent, Domain, LabelContent, ProjectBillingOwner,
                       ProviderRepairManifest, ProviderRepairQuarantine,
                       SubscriptionBinding, TransitionLog, WebhookAttempt,
                       WebhookDelivery, WebhookEndpoint, WebhookEvent)


def create_outbound_delivery_schema(connection: Connection) -> None:
    """Apply block E without replacing Prompt D's shared event table."""
    for model in (WebhookEndpoint, WebhookEvent, WebhookDelivery, WebhookAttempt):
        cast(Table, model.__table__).create(connection, checkfirst=True)
    if "key_version" not in {c["name"] for c in inspect(connection).get_columns("webhook_attempt")}:
        connection.execute(text("ALTER TABLE webhook_attempt ADD COLUMN key_version INTEGER"))
    if "terminal_at" not in {c["name"] for c in inspect(connection).get_columns("webhook_delivery")}:
        dtype = "TIMESTAMPTZ" if connection.dialect.name == "postgresql" else "DATETIME"
        connection.execute(text(f"ALTER TABLE webhook_delivery ADD COLUMN terminal_at {dtype}"))
        connection.execute(text("UPDATE webhook_delivery SET terminal_at=CURRENT_TIMESTAMP WHERE state='cancelled'"))


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
            text TEXT, notes TEXT, review_notes TEXT,
            recommended_action VARCHAR(200), actual_action VARCHAR(200),
            verified_outcome BOOLEAN, confidence FLOAT, scored_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            verified_at DATETIME, verified_by_key_id CHAR(32) REFERENCES api_keys(id),
            verification_reason VARCHAR(1000),
            prior_revision_id VARCHAR(200), revision_actor VARCHAR(200),
            revision_by_key_id CHAR(32) REFERENCES api_keys(id),
            revision_at TIMESTAMP, idempotency_token VARCHAR(200),
            CONSTRAINT uq_label_log_domain_label UNIQUE (domain_id, label_id))"""))
        columns = ("id domain_id tenant_id superseded_by label_id annotation_id source_task_id source_updated_at "
                   "annotator_id category factors_json text notes review_notes recommended_action actual_action "
                   "verified_outcome confidence scored_at verified_at verified_by_key_id verification_reason prior_revision_id "
                   "revision_actor revision_by_key_id revision_at idempotency_token").split()
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
            manifest = session.get(ProviderRepairManifest, key.id)
            if manifest is not None:
                modern_intent = session.scalar(select(CheckoutIntent.id).where(
                    (CheckoutIntent.payer == key.id) | (CheckoutIntent.purchaser == key.id)).limit(1))
                if modern_intent is not None and session.get(ProviderRepairQuarantine, key.id) is None:
                    session.add(ProviderRepairQuarantine(
                        key_id=key.id, tenant_id=key.tenant_id,
                        reason_code="modern_checkout_manifest_conflict", quarantined_at=now))
                continue
            if session.get(ProviderRepairQuarantine, key.id) is not None:
                continue
            customer, subscription = key.paddle_customer_id, key.paddle_subscription_id
            siblings = session.scalars(select(ApiKey).where(ApiKey.tenant_id == key.tenant_id)).all()
            owner = session.get(ProjectBillingOwner, key.tenant_id)
            binding = session.get(SubscriptionBinding, subscription) if subscription else None
            modern_intent = session.scalar(select(CheckoutIntent.id).where(
                (CheckoutIntent.payer == key.id) | (CheckoutIntent.purchaser == key.id)).limit(1))
            # A binding already created by checkout is current provider history,
            # never evidence of a pre-A repair eligible for intent-free delivery.
            if (binding is not None and binding.payer == key.id
                    and binding.customer_id == customer and binding.retired_at is None
                    and key.id not in legacy_ids):
                continue
            if modern_intent is not None:
                session.add(ProviderRepairQuarantine(
                    key_id=key.id, tenant_id=key.tenant_id,
                    reason_code="modern_checkout_provider_conflict", quarantined_at=now))
                continue
            reason = None
            if key.id in legacy_ids:
                reason = "legacy_provider_conflict" if customer or subscription else "legacy_provider_unmapped"
            elif not customer or not customer.startswith("ctm_") or not subscription or not subscription.startswith("sub_"):
                reason = "unconfirmed_provider_ids"
            elif owner is None and len(siblings) != 1:
                reason = "ambiguous_payer"
            elif owner is not None and owner.billing_key_id != key.id:
                reason = "owner_mismatch"
            elif binding is not None and (binding.payer != key.id or binding.customer_id != customer
                                          or binding.retired_at is not None):
                reason = "binding_mismatch"
            elif subscription and session.scalar(select(SubscriptionBinding.subscription_id).where(
                    SubscriptionBinding.payer == key.id,
                    SubscriptionBinding.retired_at.is_(None),
                    SubscriptionBinding.subscription_id != subscription)) is not None:
                reason = "current_binding_conflict"
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


def rollback_notes_guidelines(connection: Connection) -> None:
    """Repeat-safe rollback for the Notes + Guidelines additive migration."""
    for table, columns in (("label_log", ("review_notes", "notes")),
                           ("domains", ("guidelines_updated_at",))):
        if not inspect(connection).has_table(table):
            continue
        existing = {column["name"] for column in inspect(connection).get_columns(table)}
        for column in columns:
            if column in existing:
                connection.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {column}")


def normalize_historical_tombstones(connection: Connection) -> None:
    """Make already-empty historical tenants terminal without harming live data."""
    if not inspect(connection).has_table("api_keys") or not inspect(connection).has_table("domains"):
        return
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        tenants = set(session.scalars(select(ApiKey.tenant_id).where(
            ApiKey.subscription_state == "cleaned_up")))
        for tenant_id in tenants:
            if session.scalar(select(Domain.id).where(Domain.tenant_id == tenant_id).limit(1)) is not None:
                continue
            siblings = list(session.scalars(select(ApiKey).where(ApiKey.tenant_id == tenant_id)))
            if any(entitlement_decision(sibling).protects_tenant for sibling in siblings):
                continue
            for sibling in siblings:
                sibling.is_active = False
                sibling.subscription_state = "cleaned_up"
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
                 binding.retired_at is not None or
                 owner.trial_started_at.replace(tzinfo=timezone.utc) != manifest.trial_started_at.replace(tzinfo=timezone.utc) or
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
                        _upgrade_timestamps(sync_connection, "domains", ("guidelines_updated_at",))
                        for column, definition in {
                            "description": "TEXT",
                            "status": "VARCHAR(16) NOT NULL DEFAULT 'active'",
                            "automation_enabled": "BOOLEAN NOT NULL DEFAULT false",
                            "confidence_floor": "FLOAT NOT NULL DEFAULT 0.95",
                            "settings_version": "INTEGER NOT NULL DEFAULT 1",
                            "content_type": "VARCHAR(20) NOT NULL DEFAULT 'text'",
                            "label_schema": "VARCHAR(20) NOT NULL DEFAULT 'single'",
                            "modality_enforced": "BOOLEAN NOT NULL DEFAULT false",
                        }.items():
                            if column not in names:
                                if (sync_connection.dialect.name == "postgresql" and column in {
                                        "content_type", "label_schema", "modality_enforced"}):
                                    sync_connection.execute(text(
                                        f"ALTER TABLE domains ADD COLUMN IF NOT EXISTS {column} {definition}"))
                                else:
                                    sync_connection.execute(text(
                                        f"ALTER TABLE domains ADD COLUMN {column} {definition}"))
                        checks = {
                            "ck_domain_status": "status IN ('active','archived','completed')",
                            "ck_domain_confidence_floor": "confidence_floor BETWEEN 0.80 AND 0.99",
                            "ck_domain_settings_version": "settings_version >= 1",
                            "ck_domains_modality_pair":
                                "(content_type='text' AND label_schema IN ('single','multi','ner')) OR "
                                "(content_type='image' AND label_schema IN ('single','multi'))",
                        }
                        if sync_connection.dialect.name == "postgresql":
                            existing_checks = {row["name"] for row in inspect(sync_connection).get_check_constraints("domains")}
                            for name, predicate in checks.items():
                                if name not in existing_checks:
                                    not_valid = " NOT VALID" if name == "ck_domains_modality_pair" else ""
                                    sync_connection.execute(text(
                                        f"ALTER TABLE domains ADD CONSTRAINT {name} CHECK ({predicate}){not_valid}"))
                                    if name == "ck_domains_modality_pair":
                                        sync_connection.execute(text(
                                            "ALTER TABLE domains VALIDATE CONSTRAINT ck_domains_modality_pair"))
                        elif sync_connection.dialect.name == "sqlite":
                            # SQLite cannot add CHECK constraints to a populated table. Equivalent
                            # insert/update guards avoid rebuilding a referenced project table.
                            sqlite_checks = {
                                "ck_domain_status": "NEW.status IN ('active','archived','completed')",
                                "ck_domain_confidence_floor": "NEW.confidence_floor BETWEEN 0.80 AND 0.99",
                                "ck_domain_settings_version": "NEW.settings_version >= 1",
                                "ck_domains_modality_pair":
                                    "(NEW.content_type='text' AND NEW.label_schema IN ('single','multi','ner')) OR "
                                    "(NEW.content_type='image' AND NEW.label_schema IN ('single','multi'))",
                            }
                            for name, predicate in sqlite_checks.items():
                                for operation in ("INSERT", "UPDATE"):
                                    trigger = f"{name}_{operation.lower()}"
                                    sync_connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
                                    sync_connection.execute(text(
                                        f"CREATE TRIGGER {trigger} BEFORE {operation} ON domains "
                                        f"WHEN NOT ({predicate}) BEGIN SELECT RAISE(ABORT, '{name}'); END"))
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
                        for column in ("notes", "review_notes"):
                            if column not in names:
                                sync_connection.execute(text(
                                    f"ALTER TABLE label_log ADD COLUMN {column} TEXT"))
                        for column, definition in {
                            "prior_revision_id": "VARCHAR(200)", "revision_actor": "VARCHAR(200)",
                            "revision_by_key_id": ("UUID" if sync_connection.dialect.name == "postgresql"
                                                   else "CHAR(32) REFERENCES api_keys(id)"),
                            "verified_by_key_id": ("UUID" if sync_connection.dialect.name == "postgresql"
                                                   else "CHAR(32) REFERENCES api_keys(id)"),
                            "idempotency_token": "VARCHAR(200)",
                            "verification_reason": "VARCHAR(1000)",
                        }.items():
                            if column not in names:
                                sync_connection.execute(text(f"ALTER TABLE label_log ADD COLUMN {column} {definition}"))
                        if sync_connection.dialect.name == "postgresql" and inspector.has_table("api_keys"):
                            foreign_keys = inspect(sync_connection).get_foreign_keys("label_log")
                            for key_column in ("revision_by_key_id", "verified_by_key_id"):
                                if not any(key_column in (fk.get("constrained_columns") or [])
                                           for fk in foreign_keys):
                                    sync_connection.execute(text(
                                        f"ALTER TABLE label_log ADD CONSTRAINT fk_label_log_{key_column} "
                                        f"FOREIGN KEY ({key_column}) REFERENCES api_keys(id)"))
                        _upgrade_timestamps(sync_connection, table, ("revision_at", "source_updated_at"))
                        if sync_connection.dialect.name == "sqlite" and inspector.has_table("api_keys"):
                            existing_fks = inspect(sync_connection).get_foreign_keys("label_log")
                            if any(not any(key_column in (fk.get("constrained_columns") or [])
                                           for fk in existing_fks)
                                   for key_column in ("revision_by_key_id", "verified_by_key_id")):
                                _rebuild_sqlite_label_log(sync_connection)
                        if sync_connection.dialect.name == "postgresql":
                            for column in ("category", "recommended_action", "confidence", "scored_at"):
                                sync_connection.execute(text(f"ALTER TABLE label_log ALTER COLUMN {column} DROP NOT NULL"))
                        elif any(column["name"] in {"category", "recommended_action", "confidence", "scored_at"}
                                 and not column["nullable"] for column in inspector.get_columns("label_log")):
                            _rebuild_sqlite_label_log(sync_connection)
                        checks = {
                            "ck_label_log_recommended_action_length":
                                "recommended_action IS NULL OR length(recommended_action) <= 200",
                            "ck_label_log_actual_action_length":
                                "actual_action IS NULL OR length(actual_action) <= 200",
                        }
                        if sync_connection.dialect.name == "postgresql":
                            existing_checks = {row["name"] for row in inspect(sync_connection).get_check_constraints("label_log")}
                            for name, predicate in checks.items():
                                if name not in existing_checks:
                                    sync_connection.execute(text(
                                        f"ALTER TABLE label_log ADD CONSTRAINT {name} CHECK ({predicate})"))
                        else:
                            for name, predicate in checks.items():
                                for operation in ("INSERT", "UPDATE"):
                                    trigger = f"{name}_{operation.lower()}"
                                    sync_connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
                                    sync_connection.execute(text(
                                        f"CREATE TRIGGER {trigger} BEFORE {operation} ON label_log "
                                        f"WHEN NOT ({predicate.replace('recommended_action', 'NEW.recommended_action').replace('actual_action', 'NEW.actual_action')}) "
                                        f"BEGIN SELECT RAISE(ABORT, '{name}'); END"))
                        duplicate = sync_connection.execute(text(
                            "SELECT domain_id, prior_revision_id FROM label_log "
                            "WHERE prior_revision_id IS NOT NULL "
                            "GROUP BY domain_id, prior_revision_id HAVING count(*) > 1 LIMIT 1")).first()
                        if duplicate is not None:
                            raise RuntimeError("Duplicate predecessor revisions require project reconciliation")
                        sync_connection.execute(text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS uq_revision_predecessor "
                            "ON label_log (domain_id, prior_revision_id) "
                            "WHERE prior_revision_id IS NOT NULL"))
                    sync_connection.execute(text(
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)"))
                if inspector.has_table("label_content") and sync_connection.dialect.name == "postgresql":
                    image_type = next((column["type"] for column in
                                       inspect(sync_connection).get_columns("label_content")
                                       if column["name"] == "image_url"), None)
                    if isinstance(image_type, String) and image_type.length is not None:
                        sync_connection.execute(text(
                            "ALTER TABLE label_content ALTER COLUMN image_url TYPE TEXT"))
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
                    if "reproof_required" not in names:
                        sync_connection.execute(text(
                            "ALTER TABLE api_keys ADD COLUMN reproof_required BOOLEAN NOT NULL DEFAULT false"))
                    sync_connection.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_key_owner ON api_keys (tenant_id, id)"))
                    if sync_connection.dialect.name == "postgresql":
                        constraints = {row["name"] for row in inspect(sync_connection).get_unique_constraints("api_keys")}
                        if "uq_key_owner" not in constraints:
                            sync_connection.execute(text(
                                "ALTER TABLE api_keys ADD CONSTRAINT uq_key_owner UNIQUE USING INDEX uq_key_owner"))
                    additions = {
                        "tier": "VARCHAR(20) NOT NULL DEFAULT 'trial'",
                        "paddle_customer_id": "VARCHAR(200)",
                        "paddle_subscription_id": "VARCHAR(200)",
                        "paddle_event_id": "VARCHAR(200)",
                        "contact_email": "VARCHAR(200)",
                        "signup_email": "VARCHAR(200)",
                        "signup_reconciliation_reference": "VARCHAR(200)",
                        "labels_this_month": "INTEGER NOT NULL DEFAULT 0",
                        "labels_month_key": "VARCHAR(7) NOT NULL DEFAULT ''",
                        "labels_today": "INTEGER NOT NULL DEFAULT 0",
                        "labels_day_key": "VARCHAR(10) NOT NULL DEFAULT ''",
                    }
                    _upgrade_timestamps(sync_connection, "api_keys", (
                        "trial_expiring_email_sent_at", "trial_expired_email_sent_at",
                        "cancelled_at", "paddle_event_occurred_at", "email_verified_at"))
                    for column, definition in additions.items():
                        if column not in names:
                            sync_connection.execute(text(
                                f"ALTER TABLE api_keys ADD COLUMN {column} {definition}"))
                    # Before challenge-based issuance, signup sent the same live key to
                    # an unverified requester and mailbox. Neither holder can be trusted.
                    # Require a mailbox proof and rotate the digest before reuse.
                    if "email_verified_at" not in names:
                        sync_connection.execute(text(
                            "UPDATE api_keys SET is_active = false, reproof_required = true "
                            "WHERE contact_email IS NOT NULL AND email_verified_at IS NULL "
                            "AND is_active = true"))
                    sync_connection.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_contact_email "
                        "ON api_keys (lower(contact_email)) WHERE contact_email IS NOT NULL"))
                    sync_connection.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_signup_email "
                        "ON api_keys (lower(signup_email)) WHERE signup_email IS NOT NULL"))
                    sync_connection.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_paddle_customer_id "
                        "ON api_keys (paddle_customer_id) WHERE paddle_customer_id IS NOT NULL"))
            def fresh_install(sync_connection: Connection) -> bool:
                inspector = inspect(sync_connection)
                if inspector.has_table("dlj_fresh_install"):
                    return True
                if any(inspector.has_table(name) for name in ("api_keys", "domains", "label_log")):
                    return False
                sync_connection.execute(text("CREATE TABLE dlj_fresh_install (id INTEGER PRIMARY KEY)"))
                return True

            modern_only = await connection.run_sync(fresh_install)
            await connection.run_sync(upgrade)
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(create_outbound_delivery_schema)
            if not modern_only:
                await connection.run_sync(repair_provider_links)
                await connection.run_sync(normalize_historical_tombstones)
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
