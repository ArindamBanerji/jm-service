"""Public signup, key delivery, and trial access."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import auth
from db.connection import get_db
from db.models import Base
from labeling_router import router as labeling_router
from rate_limit import limiter


@contextmanager
def signup_client(tmp_path, monkeypatch):
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'signup.db').as_posix()}")
    async def create_schema():
        async with db_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    asyncio.run(create_schema())
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def test_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(auth.signup_router)
    app.include_router(labeling_router)
    app.dependency_overrides[get_db] = test_db
    limiter._storage.reset()
    delivery = AsyncMock(return_value=True)
    monkeypatch.setattr(auth, "send_api_key_email", delivery)
    with TestClient(app) as client:
        yield client, delivery
    asyncio.run(db_engine.dispose())


@pytest.fixture
def client(tmp_path, monkeypatch):
    with signup_client(tmp_path, monkeypatch) as result:
        yield result


def test_registration_returns_key_and_tenant(client):
    http, _ = client
    response = http.post("/v1/auth/register", json={"email": " Test@Example.com ", "name": "Test Team"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["api_key"]) == 64
    assert body["tenant_id"]
    assert body["tier"] == "trial"
    assert body["message"] == "Save this key — it cannot be recovered."


def test_duplicate_email_is_conflict(client):
    http, _ = client
    assert http.post("/v1/auth/register", json={"email": "first@example.com"}).status_code == 201
    assert http.post("/v1/auth/register", json={"email": "FIRST@example.com"}).status_code == 409


def test_invalid_email_is_unprocessable(client):
    http, _ = client
    assert http.post("/v1/auth/register", json={"email": "bad-address"}).status_code == 422


def test_rate_limit_five_per_minute(client):
    http, _ = client
    statuses = [http.post("/v1/auth/register", json={"email": f"rate{i}@example.com"}).status_code
                for i in range(6)]
    assert statuses == [201] * 5 + [429]


def test_registered_key_can_score(client):
    http, _ = client
    key = http.post("/v1/auth/register", json={"email": "score@example.com"}).json()["api_key"]
    response = http.post("/v1/labels/ingest", headers={"X-Api-Key": key}, json={
        "domain_id": "signup-demo", "label_id": "one", "category": "TEST",
        "factors": {"confidence": 0.8, "difficulty": 0.2}})
    assert response.status_code == 200, response.text


def test_key_delivery_called(client):
    http, delivery = client
    response = http.post("/v1/auth/register", json={"email": "mail@example.com"})
    assert response.status_code == 201
    delivery.assert_awaited_once_with("mail@example.com", response.json()["api_key"])
