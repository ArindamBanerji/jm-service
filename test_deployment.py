"""Deployment readiness and container configuration contracts."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import jm_service
from db.connection import normalize_database_url


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'labeling.db').as_posix()}")
    monkeypatch.setattr(jm_service, "labeling_engine", database)
    monkeypatch.setattr(jm_service, "DB_PATH", str(tmp_path / "legacy.db"))
    with TestClient(jm_service.app) as http:
        yield http
    import asyncio
    asyncio.run(database.dispose())


def test_health_returns_200(client: TestClient):
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["version"] == "0.2.0"


def test_health_checks_structure(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    checks = client.get("/v1/health").json()["checks"]
    assert checks == {"labeling_db": "connected", "legacy_db": "connected", "engine_hash": "verified"}
    monkeypatch.setattr(jm_service, "DB_PATH", str(ROOT / "missing" / "legacy.db"))
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["legacy_db"].startswith("error:")


def test_health_engine_hash(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    assert client.get("/v1/health").json()["checks"]["engine_hash"] == "verified"
    monkeypatch.setattr(jm_service, "labeling_engine",
                        create_async_engine("sqlite+aiosqlite:///missing/labeling.db"))
    response = client.get("/v1/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    assert response.json()["checks"]["labeling_db"].startswith("error:")


def test_dockerfile_copies_packages():
    dockerfile = (ROOT / "Dockerfile").read_text()
    for package in ("COPY *.py", "COPY label_health/", "COPY db/"):
        assert package in dockerfile
    assert 'ENTRYPOINT ["./docker-entrypoint.sh"]' in dockerfile


def test_compose_has_postgres():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "postgres:17-alpine" in compose
    assert "pg_isready -U jm -d jm_labeling" in compose
    assert "condition: service_healthy" in compose


def test_compose_database_url():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "postgresql+asyncpg://jm:jm_dev@postgres:5432/jm_labeling" in compose
    assert "JM_DB_PATH: /data/jm_tenants.db" in compose
    assert "pgdata:" in compose and "jm-data:" in compose


def test_entrypoint_exists():
    script = ROOT / "docker-entrypoint.sh"
    assert script.is_file() and script.read_text().strip()
    assert script.read_bytes().startswith(b"#!/bin/sh")


def test_entrypoint_runs_migration():
    script = (ROOT / "docker-entrypoint.sh").read_text()
    assert "from db.migrate import run_migration; run_migration()" in script
    assert 'exec uvicorn jm_service:app --host 0.0.0.0 --port "${PORT:-8000}"' in script


@pytest.mark.parametrize("scheme", ["postgresql", "postgres"])
def test_url_normalization_postgres_schemes(scheme: str):
    url, args = normalize_database_url(f"{scheme}://jm:abc@railway-host:5432/jm_labeling")
    assert url == "postgresql+asyncpg://jm:abc@railway-host:5432/jm_labeling"
    assert args == {}


def test_url_normalization_sslmode_stripped():
    url, args = normalize_database_url("postgresql://jm:abc@host/db?sslmode=require&application_name=jm")
    assert url == "postgresql+asyncpg://jm:abc@host/db?application_name=jm"
    assert args == {"ssl": True}


def test_url_normalization_railway_internal_no_ssl():
    """Railway internal networking: SSL disabled (private network, self-signed cert)."""
    url, args = normalize_database_url(
        "postgresql://user:pass@postgres.railway.internal:5432/railway")
    assert url == "postgresql+asyncpg://user:pass@postgres.railway.internal:5432/railway"
    assert args == {"ssl": False}


def test_url_normalization_railway_internal_explicit_sslmode_wins():
    """Explicit sslmode in URL overrides Railway internal detection."""
    url, args = normalize_database_url(
        "postgresql://user:pass@postgres.railway.internal:5432/railway?sslmode=require")
    assert args == {"ssl": True}


def test_url_normalization_railway_external_ssl(monkeypatch):
    """Railway external proxy: SSL enabled."""
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    url, args = normalize_database_url(
        "postgresql://user:pass@external-host.proxy.rlwy.net:5432/railway")
    assert args == {"ssl": True}


def test_url_normalization_sqlite_unchanged():
    original = "sqlite+aiosqlite:///test.db"
    assert normalize_database_url(original) == (original, {})


def test_dockerignore_and_frontend_artifacts():
    assert "__pycache__" in (ROOT / ".dockerignore").read_text()
    assert (ROOT / "frontend" / "dist" / "index.html").is_file()
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "RUN npm run build" in dockerfile
    assert "COPY --from=frontend-build /app/frontend/dist ./frontend/dist" in dockerfile
    assert "mkdir -p /data" in dockerfile
