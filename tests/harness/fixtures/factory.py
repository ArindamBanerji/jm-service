from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth import generate_api_key, scoped_domain_id
from db import repository
from jm_core import DomainConfig, JudgmentMemoryEngine


@dataclass
class Factory:
    sessions: async_sessionmaker[AsyncSession]
    tenant: str = "contract-tenant"

    async def user(self, tenant: str | None = None) -> str:
        plain, key = generate_api_key(tenant or self.tenant, "Contract user")
        async with self.sessions.begin() as session:
            session.add(key)
        return plain

    async def domain(self, name: str = "demo", *, alias: bool = True) -> str:
        scoped = scoped_domain_id(self.tenant, name)
        config = DomainConfig(scoped, name, ["quality", "difficulty"], ["A", "B"], ["approve", "reject"])
        async with self.sessions.begin() as session:
            await repository.create_domain(session, scoped, name, config, self.tenant, name if alias else None)
        return scoped

    async def engine(self, domain: str) -> JudgmentMemoryEngine:
        async with self.sessions.begin() as session:
            session.info["tenant_id"] = self.tenant
            engine = await repository.load_or_create_engine(session, domain)
            await repository.save_engine_state(session, domain, None, engine)
            return engine

    async def label(self, label_id: str = "L1", domain: str = "demo") -> str:
        scoped = scoped_domain_id(self.tenant, domain)
        async with self.sessions.begin() as session:
            session.info["tenant_id"] = self.tenant
            engine = await repository.load_or_create_engine(session, scoped)
            await repository.score_and_persist(session, engine, scoped, label_id, None, "A",
                                               {"quality": .8, "difficulty": .2}, "Sample text")
        return label_id


@dataclass
class Wire:
    client: AsyncClient
    factory: Factory
    directory: Path
    observers: dict[str, Callable[[], Awaitable[None]]] = field(default_factory=dict)

    async def observe(self, request_id: str) -> None:
        observer = self.observers[request_id]
        await observer()
        del self.observers[request_id]

    async def request(self, method: str, path: str, *, status: int = 200,
                      before_send: Callable[[], Awaitable[None]] | None = None,
                      omit_api_key: bool = False, **kwargs: Any) -> Response:
        request_id = uuid4().hex if before_send is not None else None
        if request_id is not None and before_send is not None:
            self.observers[request_id] = before_send
            kwargs["headers"] = {**kwargs.get("headers", {}), "X-Harness-Request-Id": request_id}
        try:
            if omit_api_key:
                outgoing = self.client.build_request(method, path, **kwargs)
                outgoing.headers.pop("X-Api-Key", None)
                response = await self.client.send(outgoing)
            else:
                response = await self.client.request(method, path, **kwargs)
            assert response.status_code == status, (method, path, response.status_code, status)
            assert request_id is None or request_id not in self.observers, "Missing ASGI response-start observation"
            return response
        finally:
            if request_id is not None:
                self.observers.pop(request_id, None)

    def committed(self, query: str, expected: object = 1) -> Callable[[], Awaitable[None]]:
        async def inspect() -> None:
            async with self.factory.sessions() as fresh:
                assert await fresh.scalar(text(query)) == expected, query
        return inspect


def shape(value: Any, schema: Any) -> None:
    """Freeze required keys and JSON types. Allow additive fields."""
    if isinstance(schema, dict):
        assert isinstance(value, dict), value
        for key, child in schema.items():
            assert key in value, key
            shape(value[key], child)
    elif isinstance(schema, list):
        assert isinstance(value, list), value
        for item in value:
            shape(item, schema[0])
    else:
        types = schema if isinstance(schema, tuple) else (schema,)
        assert type(value) in types, (value, types)


NULL = type(None)
NUMBER = (int, float)
OPTIONAL_NUMBER = (int, float, type(None))
TIER_STATUS = {
    "tier": str, "category": str, "verified_count": int, "accuracy": OPTIONAL_NUMBER,
    "conservation_gate_pass": bool, "conservation_reason": (str, NULL),
    "next_tier": (str, NULL), "next_tier_requirements": (str, NULL), "recommended_action_policy": str,
}
