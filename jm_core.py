"""
jm_core.py — Standalone Judgment Memory Engine

The complete JM mechanism extracted for service deployment:
  - Centroid tensor (μ) with L2 scoring
  - Asymmetric learning rates (η_confirm / η_override)
  - Welford online variance (σ diagnostic)
  - Three-layer conservation gate
  - State export/import (JSON-serializable)

This is the engine. No framework dependencies. No LLM calls.
Pure geometry + arithmetic.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional


# ─── Data structures ───────────────────────────────────────────────

@dataclass
class DomainConfig:
    """Defines the decision space for one domain (one customer use case)."""
    domain_id: str
    name: str
    factors: list[str]           # e.g. ["urgency", "spend", "supplier_risk", ...]
    categories: list[str]        # e.g. ["invoice", "po", "contract", ...]
    actions: list[str]           # e.g. ["approve", "escalate", "reject", "hold"]
    factor_ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    # optional per-factor min/max for normalization

    @property
    def n_factors(self) -> int:
        return len(self.factors)

    @property
    def n_categories(self) -> int:
        return len(self.categories)

    @property
    def n_actions(self) -> int:
        return len(self.actions)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DomainConfig":
        return cls(**d)


@dataclass
class WelfordState:
    """Online variance tracker (Welford's algorithm)."""
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    @property
    def variance(self) -> float:
        if self.count < 2:
            return 0.0
        return self.m2 / (self.count - 1)

    @property
    def std(self) -> float:
        return math.sqrt(self.variance)

    def update(self, x: float) -> None:
        self.count += 1
        delta = x - self.mean
        self.mean += delta / self.count
        delta2 = x - self.mean
        self.m2 += delta * delta2


@dataclass
class ConservationState:
    """Three-layer conservation gate state."""
    # Layer 1: aggregate
    category_coverage: dict[str, int] = field(default_factory=dict)  # category -> verified count
    total_verified: int = 0
    rolling_accuracy: float = 0.0   # q: rolling over last W decisions
    accuracy_window: list[bool] = field(default_factory=list)  # last W outcomes
    window_size: int = 400

    # Layer 2: per-factor delta (G-REL)
    per_factor_accuracy: dict[str, float] = field(default_factory=dict)
    m_rel: float = 0.7  # relative baseline multiplier

    # Layer 3: rate-of-change (G-RATE)
    short_window: list[bool] = field(default_factory=list)
    w_short: int = 20
    m_rate: float = 0.85
    baseline_accuracy: float = 0.0  # set at deployment approval

    def update(self, correct: bool, category: str) -> None:
        """Update conservation state with a verified outcome."""
        self.total_verified += 1
        self.category_coverage[category] = self.category_coverage.get(category, 0) + 1

        # Rolling accuracy window
        self.accuracy_window.append(correct)
        if len(self.accuracy_window) > self.window_size:
            self.accuracy_window.pop(0)
        self.rolling_accuracy = sum(self.accuracy_window) / len(self.accuracy_window)

        # Short window for rate detection
        self.short_window.append(correct)
        if len(self.short_window) > self.w_short:
            self.short_window.pop(0)

        # Set baseline on first full window
        if self.total_verified == self.window_size and self.baseline_accuracy == 0.0:
            self.baseline_accuracy = self.rolling_accuracy

    def check_gate(self, n_categories: int) -> tuple[bool, str]:
        """Check all three conservation layers. Returns (pass, reason)."""
        if self.total_verified < 50:
            return True, "warmup"  # not enough data to gate yet

        # Layer 1: aggregate α·q·V ≥ θ_min
        alpha = len(self.category_coverage) / max(n_categories, 1)
        q = self.rolling_accuracy
        v = self.total_verified
        theta_min = 23.53 / max(alpha * v, 0.001)
        aqv = alpha * q * v

        if aqv < theta_min:
            return False, f"L1_aggregate: α·q·V={aqv:.2f} < θ_min={theta_min:.2f}"

        # Layer 2: per-factor delta (simplified — check rolling vs baseline)
        if self.baseline_accuracy > 0:
            if self.rolling_accuracy < self.m_rel * self.baseline_accuracy:
                return False, f"L2_drift: q={self.rolling_accuracy:.3f} < {self.m_rel}×baseline={self.m_rel * self.baseline_accuracy:.3f}"

        # Layer 3: rate-of-change
        if len(self.short_window) >= self.w_short and self.baseline_accuracy > 0:
            short_acc = sum(self.short_window) / len(self.short_window)
            if short_acc < self.m_rate * self.baseline_accuracy:
                return False, f"L3_rate: short_acc={short_acc:.3f} < {self.m_rate}×baseline={self.m_rate * self.baseline_accuracy:.3f}"

        return True, "clear"


@dataclass
class ScoreResult:
    """Result of scoring an input against the centroid geometry."""
    decision_id: str
    recommended_action: str
    confidence: float
    all_scores: dict[str, float]   # action -> score
    gate_status: str               # "clear", "warmup", "PAUSED: <reason>"
    category: str
    factors: dict[str, float]


@dataclass
class LearnResult:
    """Result of learning from a verified outcome."""
    decision_id: str
    centroid_moved: bool
    old_distance: float
    new_distance: float
    learning_rate_used: float
    gate_status: str


# ─── The Engine ────────────────────────────────────────────────────

class JudgmentMemoryEngine:
    """
    The complete JM mechanism.

    State is a dict of centroids keyed by (category, action),
    each being a list of floats in factor-space.

    Scoring: P(a|f,c) = softmax(-‖f - μ[c,a]‖² / τ)
    Learning: μ[c,a] ← μ[c,a] + η·(f - μ[c,a])
    """

    def __init__(
        self,
        config: DomainConfig,
        tau: float = 0.1,
        eta_confirm: float = 0.05,
        eta_override: float = 0.01,
    ):
        self.config = config
        self.tau = tau
        self.eta_confirm = eta_confirm
        self.eta_override = eta_override

        # Initialize centroids — start at center of factor space
        self.centroids: dict[str, list[float]] = {}
        for cat in config.categories:
            for act in config.actions:
                key = f"{cat}|{act}"
                # Initialize with slight random spread around 0.5
                self.centroids[key] = [0.5] * config.n_factors

        # Per-factor variance trackers (Welford)
        self.variance_trackers: dict[str, WelfordState] = {
            f: WelfordState() for f in config.factors
        }

        # Conservation gate
        self.conservation = ConservationState()

        # Decision log (for audit trail)
        self.decision_log: dict[str, dict] = {}

        # Metrics
        self.total_decisions: int = 0
        self.total_correct: int = 0

    def _l2_distance(self, a: list[float], b: list[float]) -> float:
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    def _softmax_scores(self, distances: dict[str, float]) -> dict[str, float]:
        """Convert L2 distances to softmax probabilities."""
        # Negate distances (closer = higher score)
        neg_sq = {k: -(d ** 2) / self.tau for k, d in distances.items()}
        max_val = max(neg_sq.values())
        exp_vals = {k: math.exp(v - max_val) for k, v in neg_sq.items()}
        total = sum(exp_vals.values())
        return {k: v / total for k, v in exp_vals.items()}

    def score(self, factors: dict[str, float], category: str) -> ScoreResult:
        """
        Score an input against the centroid geometry.

        factors: dict mapping factor names to values (0-1 normalized)
        category: which category this decision belongs to
        """
        decision_id = str(uuid.uuid4())[:12]
        factor_vec = [factors.get(f, 0.5) for f in self.config.factors]

        # Compute L2 distance to each action's centroid for this category
        distances: dict[str, float] = {}
        for act in self.config.actions:
            key = f"{category}|{act}"
            centroid = self.centroids.get(key)
            if centroid is None:
                distances[act] = 999.0  # unknown category-action pair
            else:
                distances[act] = self._l2_distance(factor_vec, centroid)

        # Softmax over distances
        scores = self._softmax_scores(distances)

        # Best action
        best_action = max(scores, key=scores.get)  # type: ignore[arg-type]
        confidence = scores[best_action]

        # Conservation gate check
        gate_pass, gate_reason = self.conservation.check_gate(self.config.n_categories)
        gate_status = "clear" if gate_pass else f"PAUSED: {gate_reason}"
        if gate_reason == "warmup":
            gate_status = "warmup"

        self.total_decisions += 1

        # Log the decision
        self.decision_log[decision_id] = {
            "factors": factors,
            "factor_vec": factor_vec,
            "category": category,
            "recommended_action": best_action,
            "confidence": confidence,
            "gate_status": gate_status,
        }

        return ScoreResult(
            decision_id=decision_id,
            recommended_action=best_action,
            confidence=confidence,
            all_scores=scores,
            gate_status=gate_status,
            category=category,
            factors=factors,
        )

    def learn(
        self,
        decision_id: str,
        actual_action: str,
        confirmed: bool = True,
    ) -> LearnResult:
        """
        Learn from a verified outcome.

        decision_id: from a prior score() call
        actual_action: what actually happened / was correct
        confirmed: True = human confirms recommendation was right,
                   False = human overrides
        """
        log_entry = self.decision_log.get(decision_id)
        if log_entry is None:
            raise ValueError(f"Unknown decision_id: {decision_id}")

        category = log_entry["category"]
        factor_vec = log_entry["factor_vec"]
        recommended = log_entry["recommended_action"]

        # Determine learning rate
        eta = self.eta_confirm if confirmed else self.eta_override

        # The centroid to update is (category, actual_action)
        key = f"{category}|{actual_action}"
        centroid = self.centroids[key]

        # Record old distance
        old_dist = self._l2_distance(factor_vec, centroid)

        # Update: μ ← μ + η·(f − μ)
        new_centroid = [
            c + eta * (f - c)
            for c, f in zip(centroid, factor_vec)
        ]
        self.centroids[key] = new_centroid

        new_dist = self._l2_distance(factor_vec, new_centroid)

        # Update variance trackers
        for i, factor_name in enumerate(self.config.factors):
            self.variance_trackers[factor_name].update(factor_vec[i])

        # Update conservation state
        was_correct = (recommended == actual_action)
        if was_correct:
            self.total_correct += 1
        self.conservation.update(was_correct, category)

        gate_pass, gate_reason = self.conservation.check_gate(self.config.n_categories)

        return LearnResult(
            decision_id=decision_id,
            centroid_moved=True,
            old_distance=old_dist,
            new_distance=new_dist,
            learning_rate_used=eta,
            gate_status="clear" if gate_pass else f"PAUSED: {gate_reason}",
        )

    def diagnostics(self) -> dict:
        """Return the full diagnostic state — noise fingerprint, conservation, centroids."""
        noise_fingerprint = {}
        for f in self.config.factors:
            w = self.variance_trackers[f]
            noise_fingerprint[f] = {
                "mean": round(w.mean, 4),
                "std": round(w.std, 4),
                "n": w.count,
            }

        accuracy = self.total_correct / max(self.total_decisions, 1)

        gate_pass, gate_reason = self.conservation.check_gate(self.config.n_categories)

        return {
            "domain": self.config.name,
            "total_decisions": self.total_decisions,
            "total_correct": self.total_correct,
            "accuracy": round(accuracy, 4),
            "rolling_accuracy": round(self.conservation.rolling_accuracy, 4),
            "noise_fingerprint": noise_fingerprint,
            "gate_status": "clear" if gate_pass else f"PAUSED: {gate_reason}",
            "conservation": {
                "alpha": round(len(self.conservation.category_coverage) / max(self.config.n_categories, 1), 3),
                "q": round(self.conservation.rolling_accuracy, 4),
                "V": self.conservation.total_verified,
                "categories_seen": list(self.conservation.category_coverage.keys()),
            },
            "centroid_count": len(self.centroids),
        }

    # ─── State persistence ─────────────────────────────────────────

    def export_state(self) -> dict:
        """Export full engine state as a JSON-serializable dict."""
        return {
            "config": self.config.to_dict(),
            "tau": self.tau,
            "eta_confirm": self.eta_confirm,
            "eta_override": self.eta_override,
            "centroids": self.centroids,
            "variance_trackers": {
                f: {"count": w.count, "mean": w.mean, "m2": w.m2}
                for f, w in self.variance_trackers.items()
            },
            "conservation": {
                "category_coverage": self.conservation.category_coverage,
                "total_verified": self.conservation.total_verified,
                "rolling_accuracy": self.conservation.rolling_accuracy,
                "accuracy_window": self.conservation.accuracy_window,
                "baseline_accuracy": self.conservation.baseline_accuracy,
                "short_window": self.conservation.short_window,
            },
            "total_decisions": self.total_decisions,
            "total_correct": self.total_correct,
        }

    @classmethod
    def from_state(cls, state: dict) -> "JudgmentMemoryEngine":
        """Restore engine from exported state."""
        config = DomainConfig.from_dict(state["config"])
        engine = cls(
            config=config,
            tau=state.get("tau", 0.1),
            eta_confirm=state.get("eta_confirm", 0.05),
            eta_override=state.get("eta_override", 0.01),
        )
        engine.centroids = state["centroids"]
        engine.total_decisions = state.get("total_decisions", 0)
        engine.total_correct = state.get("total_correct", 0)

        # Restore variance trackers
        for f, vt in state.get("variance_trackers", {}).items():
            if f in engine.variance_trackers:
                engine.variance_trackers[f].count = vt["count"]
                engine.variance_trackers[f].mean = vt["mean"]
                engine.variance_trackers[f].m2 = vt["m2"]

        # Restore conservation state
        cs = state.get("conservation", {})
        engine.conservation.category_coverage = cs.get("category_coverage", {})
        engine.conservation.total_verified = cs.get("total_verified", 0)
        engine.conservation.rolling_accuracy = cs.get("rolling_accuracy", 0.0)
        engine.conservation.accuracy_window = cs.get("accuracy_window", [])
        engine.conservation.baseline_accuracy = cs.get("baseline_accuracy", 0.0)
        engine.conservation.short_window = cs.get("short_window", [])

        return engine

    def state_size_bytes(self) -> int:
        """How much storage this tenant's state requires."""
        return len(json.dumps(self.export_state()).encode("utf-8"))
