"""Run `python jm-service/db/migrate.py` from the parent claude_projects directory."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from sqlalchemy import Table, inspect, text
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.connection import engine
from db.models import Base, LabelContent


async def migrate() -> None:
    try:
        async with engine.begin() as connection:
            def upgrade(sync_connection):
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
                            "revision_at": "TIMESTAMP", "idempotency_token": "VARCHAR(200)",
                            "verification_reason": "VARCHAR(1000)",
                        }.items():
                            if column not in names:
                                sync_connection.execute(text(f"ALTER TABLE label_log ADD COLUMN {column} {definition}"))
                        if sync_connection.dialect.name == "postgresql":
                            for column in ("category", "recommended_action", "confidence", "scored_at"):
                                sync_connection.execute(text(f"ALTER TABLE label_log ALTER COLUMN {column} DROP NOT NULL"))
                        elif any(column["name"] in {"category", "recommended_action", "confidence", "scored_at"}
                                 and not column["nullable"] for column in inspector.get_columns("label_log")):
                            sync_connection.execute(text("""CREATE TABLE label_log_new (
                                id CHAR(32) PRIMARY KEY, domain_id VARCHAR(200) NOT NULL REFERENCES domains(domain_id),
                                tenant_id VARCHAR(200) NOT NULL DEFAULT '', superseded_by VARCHAR(200),
                                label_id VARCHAR(200) NOT NULL, annotation_id VARCHAR(200), source_task_id VARCHAR(200),
                                annotator_id VARCHAR(200), category VARCHAR(200), factors_json JSON NOT NULL,
                                text TEXT, recommended_action VARCHAR(200), actual_action VARCHAR(200),
                                verified_outcome BOOLEAN, confidence FLOAT, scored_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                                verified_at DATETIME, verification_reason VARCHAR(1000),
                                prior_revision_id VARCHAR(200), revision_actor VARCHAR(200),
                                revision_at DATETIME, idempotency_token VARCHAR(200),
                                CONSTRAINT uq_label_log_domain_label UNIQUE (domain_id, label_id))"""))
                            columns = ("id domain_id tenant_id superseded_by label_id annotation_id source_task_id "
                                       "annotator_id category factors_json text recommended_action actual_action "
                                       "verified_outcome confidence scored_at verified_at verification_reason prior_revision_id "
                                       "revision_actor revision_at idempotency_token").split()
                            selected = ", ".join(columns)
                            sync_connection.execute(text(
                                f"INSERT INTO label_log_new ({selected}) SELECT {selected} FROM label_log"))
                            sync_connection.execute(text("DROP TABLE label_log"))
                            sync_connection.execute(text("ALTER TABLE label_log_new RENAME TO label_log"))
                            for statement in (
                                "CREATE INDEX ix_label_log_domain_id ON label_log (domain_id)",
                                "CREATE INDEX ix_label_log_category ON label_log (category)",
                                "CREATE INDEX ix_label_log_domain_category_verified ON label_log (domain_id, category, verified_at)",
                            ):
                                sync_connection.execute(text(statement))
                    sync_connection.execute(text(
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)"))
                if inspector.has_table("api_keys"):
                    names = {column["name"] for column in inspector.get_columns("api_keys")}
                    legacy_provider = "_".join(("lemon", "squeezy"))
                    for suffix in ("customer_id", "subscription_id"):
                        old, new = f"{legacy_provider}_{suffix}", f"paddle_{suffix}"
                        if old in names and new not in names and sync_connection.dialect.name == "postgresql":
                            sync_connection.execute(text(
                                f"ALTER TABLE api_keys RENAME COLUMN {old} TO {new}"))
                            names.remove(old)
                            names.add(new)
                    additions = {
                        "tier": "VARCHAR(20) NOT NULL DEFAULT 'trial'",
                        "paddle_customer_id": "VARCHAR(200)",
                        "paddle_subscription_id": "VARCHAR(200)",
                        "contact_email": "VARCHAR(200)",
                        "trial_expiring_email_sent_at": "TIMESTAMP",
                        "trial_expired_email_sent_at": "TIMESTAMP",
                        "cancelled_at": "TIMESTAMP",
                        "labels_this_month": "INTEGER NOT NULL DEFAULT 0",
                        "labels_month_key": "VARCHAR(7) NOT NULL DEFAULT ''",
                        "labels_today": "INTEGER NOT NULL DEFAULT 0",
                        "labels_day_key": "VARCHAR(10) NOT NULL DEFAULT ''",
                    }
                    for column, definition in additions.items():
                        if column not in names:
                            sync_connection.execute(text(
                                f"ALTER TABLE api_keys ADD COLUMN {column} {definition}"))
                    sync_connection.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_contact_email "
                        "ON api_keys (lower(contact_email)) WHERE contact_email IS NOT NULL"))
            await connection.run_sync(upgrade)
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(lambda sync_connection:
                                      cast(Table, LabelContent.__table__).create(sync_connection, checkfirst=True))
    finally:
        await engine.dispose()


def run_migration() -> None:
    asyncio.run(migrate())


if __name__ == "__main__":
    run_migration()
