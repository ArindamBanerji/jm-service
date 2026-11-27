"""Round six regression cases, written against the failing implementation first."""
import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, StatementError

from db.connection import get_db, sanitize_database_error
from test_label_studio import client as studio_client, event, webhook, log_row
from test_resweep_fixes import client, ingest, verify, detail


def test_failed_commit_never_acknowledges_verification(client):
    assert ingest(client).status_code == 200
    factory = client.app.state.session_factory

    async def failing_db():
        async with factory() as session:
            async def fail_commit():
                raise IntegrityError('UPDATE label_log', {'key': 'secret'}, Exception('constraint'))
            session.commit = fail_commit
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    original_dependency = client.app.dependency_overrides[get_db]
    client.app.dependency_overrides[get_db] = failing_db
    try:
        with TestClient(client.app, raise_server_exceptions=False,
                        headers={'X-Api-Key': 'tasks-key'}) as raw:
            response = raw.post('/v1/labels/verify', json={
                'domain_id': 'medical', 'label_id': 'L1', 'actual_action': 'approve',
                'verified_outcome': True})
        assert response.status_code == 500, response.text
    finally:
        client.app.dependency_overrides[get_db] = original_dependency
    assert detail(client)['verified_at'] is None


def test_successful_commit_acknowledges_persisted_verification(client):
    assert ingest(client).status_code == 200
    assert verify(client, outcome=True).status_code == 200
    assert detail(client)['verified_outcome'] is True


def test_database_diagnostics_never_echo_values():
    statement = "INSERT INTO users (key) VALUES ('dlj_secret_key')"
    exc = StatementError(statement, statement, {'password': 's3cret'}, Exception(statement))
    result = sanitize_database_error(exc)
    assert 'INSERT INTO' in result
    assert 'dlj_secret_key' not in result
    assert 's3cret' not in result
    assert sanitize_database_error(Exception('postgresql://user:pw@[::1]:5432/db'))
    class DriverDetail(Exception):
        statement: str
        params = {'password': 's3cret'}
        orig = Exception("postgresql://admin:pw@[::1]:5432/db; password=s3cret")
    DriverDetail.statement = statement
    result = sanitize_database_error(DriverDetail("password=s3cret"))
    assert 's3cret' not in result and 'pw@' not in result


def test_database_diagnostic_formatter_is_total():
    class Bad(Exception):
        def __str__(self):
            raise RuntimeError('format boom')
    assert sanitize_database_error(Bad())


def test_connector_ignores_older_delivery(studio_client, monkeypatch):
    first = event()
    first['annotation']['updated_at'] = '2026-01-01T00:00:00Z'
    assert webhook(studio_client, first).status_code == 200
    newer = event(action='ANNOTATION_UPDATED', actual='reject', truth='reject')
    newer['annotation']['updated_at'] = '2026-01-02T00:00:00Z'
    newer['annotation']['completed_by'] = 8
    assert webhook(studio_client, newer).status_code == 200
    assert log_row(studio_client, 1) == ('reject', True, '8')
    from db import repository
    async def unexpected_learning(*args, **kwargs):
        raise AssertionError('stale delivery reached the learner')
    monkeypatch.setattr(repository, 'verify_and_relearn', unexpected_learning)
    monkeypatch.setattr(repository, 'verify_and_learn', unexpected_learning)
    old = event(action='ANNOTATION_UPDATED')
    old['annotation']['updated_at'] = '2026-01-01T00:00:00Z'
    conflict = webhook(studio_client, old)
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Conflicting connector delivery"
    old['annotation']['updated_at'] = '2025-12-31T00:00:00Z'
    assert webhook(studio_client, old).status_code == 200
    assert log_row(studio_client, 1) == ('reject', True, '8')
    assert webhook(studio_client, first).status_code == 200
    assert log_row(studio_client, 1) == ('reject', True, '8')


def test_billing_rejects_oversize_body_before_signature(client):
    response = client.post('/v1/billing/webhook', content=b'x' * 65537,
                           headers={'Content-Type': 'application/json'})
    assert response.status_code == 413, response.text


def test_billing_stream_without_length_stops_at_limit():
    import billing
    chunks_sent = 0

    async def receive():
        nonlocal chunks_sent
        chunks_sent += 1
        return {'type': 'http.request', 'body': b'x' * 32768, 'more_body': True}

    request: Request = Request({'type': 'http', 'method': 'POST', 'path': '/v1/billing/webhook',
                       'headers': []}, receive)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(billing.paddle_webhook(request))
    assert failure.value.status_code == 413
    assert chunks_sent == 3
