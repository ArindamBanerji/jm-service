"""Red/green round-five projection, exception, and webhook boundaries."""
import asyncio
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import dashboard_router
import db.connection as connection
import label_studio
import scheduler
from test_label_studio import event as connector_event
from test_resweep_fixes import client, detail, verify
from test_tasks import add_schema_category


def _score(client, label_id):
    response = client.post('/v1/labels/ingest', json={
        'domain_id': 'medical', 'label_id': label_id, 'category': 'A',
        'annotator_id': 'ann-1', 'factors': {'confidence': .7, 'difficulty': .2},
    })
    assert response.status_code == 200, response.text


def _profile(client):
    response = client.get('/v1/dashboard/medical/annotators')
    assert response.status_code == 200, response.text
    return response.json()['annotators'][0]


def _overview(client):
    response = client.get('/v1/dashboard/medical/overview')
    assert response.status_code == 200, response.text
    return response.json()


def test_annotator_projection(client):
    client.app.include_router(dashboard_router.router)
    _score(client, 'item-1')
    _score(client, 'item-2')
    add_schema_category(client, 'B')
    assert verify(client, label_id='item-1', outcome=True).status_code == 200
    assert verify(client, label_id='item-2', outcome=False).status_code == 200
    assert _profile(client)['accuracy'] == .5
    assert _overview(client)['overall_accuracy'] == .5

    revised = client.post('/v1/labels/medical/items/item-2/relabel', json={
        'category': 'B', 'idempotency_token': detail(client, 'item-2')['revision_id'],
    })
    assert revised.status_code == 200, revised.text
    successor = detail(client, 'item-2')
    assert successor['label_id'] != 'item-2' and successor['verified_at'] is None
    assert _profile(client)['accuracy'] == .5
    assert _overview(client)['overall_accuracy'] == .5

    assert verify(client, label_id=successor['label_id'], outcome=True).status_code == 200
    assert _profile(client)['accuracy'] == 1.0
    assert _overview(client)['overall_accuracy'] == 1.0


_URL = 'postgresql+asyncpg://admin:s3cret_p@ss@badhost:5432/db'


def _db_error():
    return OperationalError('CONNECT', {'dsn': _URL}, OSError('badhost unreachable'))


def test_request_session_exception_hides_database_password(monkeypatch):
    class FailingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def commit(self):
            raise _db_error()

        async def rollback(self):
            return None

    monkeypatch.setattr(connection, 'AsyncSessionLocal', FailingSession)

    async def exercise():
        async with connection.AsyncSessionLocal() as session:
            await connection.commit_write(session)

    with pytest.raises(Exception) as failure:
        asyncio.run(exercise())
    diagnostic = getattr(failure.value, 'detail', str(failure.value))
    assert 's3cret_p@ss' not in diagnostic
    assert 'badhost' not in diagnostic
    assert 'OperationalError' in diagnostic


def test_scheduler_log_hides_database_password(monkeypatch, caplog):
    async def fail():
        raise _db_error()

    monkeypatch.setattr(scheduler, 'send_trial_expiry_emails', fail)
    async def no_expiry():
        return 0
    monkeypatch.setattr(scheduler, 'expire_trial_keys', no_expiry)
    with caplog.at_level(logging.ERROR, logger='dlj.scheduler'):
        asyncio.run(scheduler.run_scheduled_tasks())
    assert 's3cret_p@ss' not in caplog.text
    assert 'badhost' not in caplog.text
    assert 'OperationalError' in caplog.text


def test_connector_rejects_nonstring_action(client):
    payload = connector_event()
    payload['action'] = {'x': 1}
    with TestClient(client.app, raise_server_exceptions=False, headers={
        'X-Api-Key': 'tasks-key', 'X-LS-Token': 'test-token',
    }) as raw:
        response = raw.post('/v1/label-studio/webhook', json=payload)
    assert response.status_code == 422, response.text
    assert 'action must be a string' in response.text
