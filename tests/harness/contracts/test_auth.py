import pytest
import auth
from typing import cast
from unittest.mock import AsyncMock

from ..fixtures.factory import NULL, Wire, shape

pytestmark = pytest.mark.anyio


async def test_signup(wire: Wire):
    response = await wire.request("POST", "/v1/auth/register", status=202, json={"email": "new@example.test"},
                                  omit_api_key=True,
                                  before_send=wire.committed("SELECT count(*) FROM signup_challenge WHERE email='new@example.test'"))
    shape(response.json(), {"message": str})
    assert "api_key" not in response.json()
    delivery = cast(AsyncMock, auth.send_signup_challenge_email)
    assert delivery.await_args is not None
    token = delivery.await_args.args[1]
    confirmed = await wire.request("POST", "/v1/auth/confirm", status=201,
                                   json={"token": token}, omit_api_key=True,
                                   before_send=wire.committed("SELECT count(*) FROM api_keys WHERE contact_email='new@example.test'"))
    shape(confirmed.json(), {"api_key": str, "tenant_id": str, "tier": str, "message": str})
    account = await wire.request("GET", "/v1/account", headers={"X-Api-Key": confirmed.json()["api_key"]})
    assert account.json()["tenant_id"] == confirmed.json()["tenant_id"]


async def test_admin_issue(wire: Wire):
    response = await wire.request("POST", "/v1/admin/api-keys", headers={"X-Admin-Key": "harness-admin"},
                                  omit_api_key=True,
                                  json={"tenant_id": "new", "tenant_name": "New user"},
                                  before_send=wire.committed("SELECT count(*) FROM api_keys WHERE tenant_id='new'"))
    shape(response.json(), {"tenant_id": str, "api_key": str})


async def test_account(wire: Wire):
    response = await wire.request("GET", "/v1/account")
    shape(response.json(), {"tenant_id": str, "tenant_name": str, "tier": str, "created_at": str,
                            "is_active": bool, "cancelled_at": (str, NULL), "trial_expires_at": (str, NULL),
                            "trial_expired": bool, "usage": {"labels_today": int, "labels_this_month": int,
                            "daily_cap": (int, NULL), "monthly_cap": (int, NULL), "day_key": str, "month_key": str}})


async def test_account_domains(wire: Wire):
    await wire.factory.domain()
    response = await wire.request("GET", "/v1/account/domains")
    assert response.json()
    shape(response.json(), [{"id": str, "public_domain_id": (str, NULL), "needs_name": bool}])


async def test_resolve_domain(wire: Wire):
    await wire.factory.domain(alias=False)
    response = await wire.request("POST", "/v1/account/domains/resolve", json={"domain_id": "demo"},
                                  before_send=wire.committed("SELECT public_domain_id FROM domains", "demo"))
    shape(response.json(), {"public_domain_id": str})
