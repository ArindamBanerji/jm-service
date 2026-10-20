"""
jm_service.py — Judgment Memory API (MVP)

FastAPI service wrapping the JM engine.
Multi-tenancy via API key → tenant state in SQLite.

Endpoints:
  POST /v1/register              — create a tenant, get API key
  POST /v1/domains               — create a decision domain
  GET  /v1/domains               — list domains for this tenant
  POST /v1/domains/{id}/score    — score an input
  POST /v1/domains/{id}/learn    — learn from verified outcome
  GET  /v1/domains/{id}/diagnostics — noise fingerprint, conservation
  GET  /v1/domains/{id}/state    — export centroid state
  GET  /v1/health                — service health
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator


# ─── Database (SQLite — swap for Postgres in R2) ─────────────────

DB_PATH = os.environ.get("JM_DB_PATH", "jm_tenants.db")


def init_db():
    """Create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            api_key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS domains (
            domain_id TEXT PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            config_json TEXT NOT NULL,
            state_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (tenant_key) REFERENCES tenants(api_key)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decision_log (
            decision_id TEXT PRIMARY KEY,
            domain_id TEXT NOT NULL,
            tenant_key TEXT NOT NULL,
            factors_json TEXT NOT NULL,
            category TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            confidence REAL NOT NULL,
            actual_action TEXT,
            confirmed INTEGER,
            scored_at REAL NOT NULL,
            learned_at REAL,
            FOREIGN KEY (domain_id) REFERENCES domains(domain_id)
        )
    """)
    conn.commit()
    conn.close()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ─── Pydantic models ────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str = Field("default", description="Tenant display name")


class CreateDomainRequest(BaseModel):
    name: str = Field(
        ...,
        description="Human-readable domain name (e.g. 'Procurement Decisions')",
        min_length=1,
        max_length=200,
        json_schema_extra={"example": "Procurement Decisions"},
    )
    factors: list[str] = Field(
        ...,
        description="Factor names that define the decision space (1-50). Values will be normalized to [0, 1].",
        min_length=1,
        max_length=50,
        json_schema_extra={"example": ["spend_amount", "supplier_risk", "urgency"]},
    )
    categories: list[str] = Field(
        ...,
        description="Decision categories (1-20). Each category gets its own set of centroids.",
        min_length=1,
        max_length=20,
        json_schema_extra={"example": ["invoice", "purchase_order", "contract"]},
    )
    actions: list[str] = Field(
        ...,
        description="Possible actions/outcomes (2-10). The engine learns which action fits which factor pattern.",
        min_length=2,
        max_length=10,
        json_schema_extra={"example": ["approve", "escalate", "reject", "hold"]},
    )
    factor_ranges: dict[str, list[float]] = Field(
        default_factory=dict,
        description="Optional per-factor [min, max] ranges for normalization. Defaults to [0, 1].",
    )

    @field_validator("factors", "categories", "actions")
    @classmethod
    def no_duplicates(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            dupes = [x for x in v if v.count(x) > 1]
            raise ValueError(f"Duplicate entries not allowed: {set(dupes)}")
        return v

    @field_validator("factors", "categories", "actions")
    @classmethod
    def no_empty_strings(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item.strip():
                raise ValueError("Empty strings not allowed")
        return v


class ScoreRequest(BaseModel):
    factors: dict[str, float] = Field(
        ...,
        description="Factor name → value mapping. Values outside [0, 1] will be clamped. Unknown factor names are rejected.",
        json_schema_extra={"example": {"spend_amount": 0.8, "supplier_risk": 0.3, "urgency": 0.6}},
    )
    category: str = Field(
        ...,
        description="Which decision category this input belongs to. Must match a category defined for the domain.",
        json_schema_extra={"example": "invoice"},
    )


class LearnRequest(BaseModel):
    decision_id: str = Field(
        ...,
        description="The decision_id returned from a prior /score call.",
        json_schema_extra={"example": "abc123def456"},
    )
    actual_action: str = Field(
        ...,
        description="What actually happened or was correct. Must be one of the domain's defined actions.",
        json_schema_extra={"example": "approve"},
    )
    confirmed: bool = Field(
        True,
        description="True = the recommendation was correct (η=0.05). False = human overrode it (η=0.01).",
    )


class ScoreResponse(BaseModel):
    decision_id: str = Field(..., description="Unique ID for this decision. Use it in /learn to provide the outcome.")
    recommended_action: str = Field(..., description="The action with highest centroid proximity score.")
    confidence: float = Field(..., description="Softmax probability of the recommended action (0-1).")
    all_scores: dict[str, float] = Field(..., description="All actions with their softmax scores.")
    gate_status: str = Field(..., description="Conservation gate: 'clear', 'warmup', or 'PAUSED: <reason>'.")
    category: str = Field(..., description="The category this decision was scored under.")


class LearnResponse(BaseModel):
    decision_id: str = Field(..., description="The decision that was learned from.")
    centroid_moved: bool = Field(..., description="Whether the centroid was updated.")
    old_distance: float = Field(..., description="L2 distance from input to centroid before update.")
    new_distance: float = Field(..., description="L2 distance from input to centroid after update.")
    learning_rate_used: float = Field(..., description="η used: 0.05 (confirm) or 0.01 (override).")
    gate_status: str = Field(..., description="Conservation gate status after this learn step.")


class DomainSummary(BaseModel):
    domain_id: str = Field(..., description="Unique domain identifier.")
    name: str = Field(..., description="Human-readable domain name.")
    created_at: float = Field(..., description="Unix timestamp of creation.")
    updated_at: float = Field(..., description="Unix timestamp of last update.")


class DomainListResponse(BaseModel):
    domains: list[DomainSummary] = Field(..., description="All domains belonging to this tenant.")


class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Human-readable error message.")


# ─── App ─────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(application: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Judgment Memory API",
    description=(
        "Decision intelligence that compounds. "
        "Score decisions → learn from outcomes → watch accuracy improve automatically.\n\n"
        "**Core loop**: POST /score with factors → get recommended action → "
        "POST /learn with actual outcome → centroids update → next score is smarter.\n\n"
        "**Conservation gate**: Three-layer safety mechanism prevents drift. "
        "Monitors aggregate accuracy, per-factor delta, and rate-of-change."
    ),
    version="0.1.0",
    lifespan=lifespan,
    responses={401: {"model": ErrorResponse, "description": "Invalid API key"}},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Auth ────────────────────────────────────────────────────────

def get_tenant(x_api_key: str = Header(..., description="Your API key from /register")) -> str:
    with get_db() as db:
        row = db.execute("SELECT api_key FROM tenants WHERE api_key = ?", (x_api_key,)).fetchone()
        if not row:
            raise HTTPException(401, "Invalid API key")
    return x_api_key


# ─── Engine loader ───────────────────────────────────────────────

def load_engine(domain_id: str, tenant_key: str):
    from jm_core import JudgmentMemoryEngine, DomainConfig
    with get_db() as db:
        row = db.execute(
            "SELECT state_json FROM domains WHERE domain_id = ? AND tenant_key = ?",
            (domain_id, tenant_key),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Domain {domain_id} not found")
    state = json.loads(row["state_json"])
    return JudgmentMemoryEngine.from_state(state)


def save_engine(domain_id: str, engine):
    state_json = json.dumps(engine.export_state())
    with get_db() as db:
        db.execute(
            "UPDATE domains SET state_json = ?, updated_at = ? WHERE domain_id = ?",
            (state_json, time.time(), domain_id),
        )


# ─── Validation helpers ─────────────────────────────────────────

def validate_score_input(req: ScoreRequest, engine) -> dict[str, float]:
    """Validate and sanitize score inputs. Returns clamped factor dict."""
    config = engine.config

    # Check category
    if req.category not in config.categories:
        raise HTTPException(
            422,
            f"Unknown category '{req.category}'. Valid: {config.categories}"
        )

    # Check for unknown factors
    unknown = set(req.factors.keys()) - set(config.factors)
    if unknown:
        raise HTTPException(
            422,
            f"Unknown factors: {sorted(unknown)}. Valid: {config.factors}"
        )

    # Clamp values to [0, 1]
    clamped = {}
    for k, v in req.factors.items():
        clamped[k] = max(0.0, min(1.0, float(v)))

    return clamped


def validate_learn_input(req: LearnRequest, engine, domain_id: str, tenant: str):
    """Validate learn inputs. Returns decision row from DB."""
    config = engine.config

    # Check action is valid
    if req.actual_action not in config.actions:
        raise HTTPException(
            422,
            f"Unknown action '{req.actual_action}'. Valid: {config.actions}"
        )

    # Fetch decision from DB
    with get_db() as db:
        dec_row = db.execute(
            "SELECT factors_json, category, recommended_action, learned_at "
            "FROM decision_log WHERE decision_id=? AND domain_id=? AND tenant_key=?",
            (req.decision_id, domain_id, tenant),
        ).fetchone()

    if not dec_row:
        raise HTTPException(404, f"Decision {req.decision_id} not found")

    # Reject duplicate learn
    if dec_row["learned_at"] is not None:
        raise HTTPException(
            409,
            f"Decision {req.decision_id} already has a learn result (learned_at={dec_row['learned_at']})"
        )

    return dec_row


# ─── Endpoints ───────────────────────────────────────────────────

@app.get("/v1/health", tags=["System"])
def health():
    """Service health check."""
    return {"status": "ok", "service": "judgment-memory", "version": "0.1.0"}


@app.post("/v1/register", tags=["Tenants"])
def register_tenant(req: RegisterRequest = RegisterRequest()):
    """Register a new tenant. Returns an API key for all subsequent requests."""
    api_key = f"jm_{uuid.uuid4().hex[:24]}"
    with get_db() as db:
        db.execute(
            "INSERT INTO tenants (api_key, name, created_at) VALUES (?, ?, ?)",
            (api_key, req.name, time.time()),
        )
    return {"api_key": api_key, "name": req.name}


@app.post(
    "/v1/domains",
    status_code=201,
    tags=["Domains"],
    responses={422: {"model": ErrorResponse, "description": "Validation error"}},
)
def create_domain(req: CreateDomainRequest, tenant: str = Depends(get_tenant)):
    """Create a new decision domain. Initializes centroids at the center of factor space."""
    from jm_core import JudgmentMemoryEngine, DomainConfig

    domain_id = f"dom_{uuid.uuid4().hex[:16]}"

    config = DomainConfig(
        domain_id=domain_id,
        name=req.name,
        factors=req.factors,
        categories=req.categories,
        actions=req.actions,
        factor_ranges={k: tuple(v) for k, v in req.factor_ranges.items()},
    )

    engine = JudgmentMemoryEngine(config)
    state_json = json.dumps(engine.export_state())

    with get_db() as db:
        db.execute(
            "INSERT INTO domains (domain_id, tenant_key, config_json, state_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (domain_id, tenant, json.dumps(config.to_dict()), state_json, time.time(), time.time()),
        )

    n_centroids = config.n_categories * config.n_actions
    return {
        "domain_id": domain_id,
        "name": req.name,
        "centroids_initialized": n_centroids,
        "state_size_bytes": len(state_json),
        "factors": req.factors,
        "categories": req.categories,
        "actions": req.actions,
    }


@app.get("/v1/domains", response_model=DomainListResponse, tags=["Domains"])
def list_domains(tenant: str = Depends(get_tenant)):
    """List all domains for this tenant."""
    with get_db() as db:
        rows = db.execute(
            "SELECT domain_id, config_json, created_at, updated_at FROM domains WHERE tenant_key = ?",
            (tenant,),
        ).fetchall()

    return DomainListResponse(
        domains=[
            DomainSummary(
                domain_id=r["domain_id"],
                name=json.loads(r["config_json"])["name"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]
    )


@app.post(
    "/v1/domains/{domain_id}/score",
    response_model=ScoreResponse,
    tags=["Decisions"],
    responses={
        404: {"model": ErrorResponse, "description": "Domain not found"},
        422: {"model": ErrorResponse, "description": "Invalid factors or category"},
    },
)
def score_decision(domain_id: str, req: ScoreRequest, tenant: str = Depends(get_tenant)):
    """Score an input against the centroid geometry.

    Returns the recommended action and confidence. The decision_id in the
    response must be passed to /learn when the actual outcome is known.
    Factor values are clamped to [0, 1]. Unknown factors or categories are rejected.
    """
    engine = load_engine(domain_id, tenant)

    # Validate and clamp
    clamped_factors = validate_score_input(req, engine)

    result = engine.score(clamped_factors, req.category)

    # Log the decision
    with get_db() as db:
        db.execute(
            """INSERT INTO decision_log
               (decision_id, domain_id, tenant_key, factors_json, category,
                recommended_action, confidence, scored_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (result.decision_id, domain_id, tenant, json.dumps(clamped_factors),
             req.category, result.recommended_action, result.confidence, time.time()),
        )

    save_engine(domain_id, engine)

    return ScoreResponse(
        decision_id=result.decision_id,
        recommended_action=result.recommended_action,
        confidence=result.confidence,
        all_scores=result.all_scores,
        gate_status=result.gate_status,
        category=req.category,
    )


@app.post(
    "/v1/domains/{domain_id}/learn",
    response_model=LearnResponse,
    tags=["Decisions"],
    responses={
        404: {"model": ErrorResponse, "description": "Domain or decision not found"},
        409: {"model": ErrorResponse, "description": "Decision already learned"},
        422: {"model": ErrorResponse, "description": "Invalid action"},
    },
)
def learn_outcome(domain_id: str, req: LearnRequest, tenant: str = Depends(get_tenant)):
    """Learn from a verified outcome — updates the centroid.

    Call this after a human has verified the actual outcome of a decision.
    Each decision can only be learned from once (duplicate learns are rejected).
    The actual_action must be one of the domain's defined actions.
    """
    engine = load_engine(domain_id, tenant)

    # Validate (checks action, fetches row, rejects duplicates)
    dec_row = validate_learn_input(req, engine, domain_id, tenant)

    # Re-inject the decision into the engine's in-memory log
    factors = json.loads(dec_row["factors_json"])
    category = dec_row["category"]
    factor_vec = [factors.get(f, 0.5) for f in engine.config.factors]
    engine.decision_log[req.decision_id] = {
        "factors": factors,
        "factor_vec": factor_vec,
        "category": category,
        "recommended_action": dec_row["recommended_action"],
    }

    result = engine.learn(req.decision_id, req.actual_action, req.confirmed)

    # Update decision log
    with get_db() as db:
        db.execute(
            "UPDATE decision_log SET actual_action=?, confirmed=?, learned_at=? WHERE decision_id=?",
            (req.actual_action, int(req.confirmed), time.time(), req.decision_id),
        )

    save_engine(domain_id, engine)

    return LearnResponse(
        decision_id=req.decision_id,
        centroid_moved=result.centroid_moved,
        old_distance=result.old_distance,
        new_distance=result.new_distance,
        learning_rate_used=result.learning_rate_used,
        gate_status=result.gate_status,
    )


@app.get(
    "/v1/domains/{domain_id}/diagnostics",
    tags=["Diagnostics"],
    responses={404: {"model": ErrorResponse}},
)
def get_diagnostics(domain_id: str, tenant: str = Depends(get_tenant)):
    """Get noise fingerprint, conservation gate status, accuracy metrics, and state size.

    The noise fingerprint shows per-factor Welford variance (σ), which reveals
    which factors carry signal vs. noise. The conservation gate shows whether
    the system is operating within its safety envelope.
    """
    engine = load_engine(domain_id, tenant)
    diag = engine.diagnostics()
    diag["state_size_bytes"] = engine.state_size_bytes()
    return diag


@app.get(
    "/v1/domains/{domain_id}/state",
    tags=["Diagnostics"],
    responses={404: {"model": ErrorResponse}},
)
def export_state(domain_id: str, tenant: str = Depends(get_tenant)):
    """Export full engine state as JSON for backup or migration.

    The state includes all centroids, variance trackers, conservation gate state,
    and config. Can be imported into another engine instance.
    """
    engine = load_engine(domain_id, tenant)
    return engine.export_state()


# ─── Run ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8100)
