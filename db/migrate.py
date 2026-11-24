"""Run `python jm-service/db/migrate.py` from the parent claude_projects directory."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.connection import engine
from db.models import Base


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
    finally:
        await engine.dispose()


def run_migration() -> None:
    asyncio.run(migrate())


if __name__ == "__main__":
    run_migration()
