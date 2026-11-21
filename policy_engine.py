"""Evidence-based labeling autonomy tiers."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from jm_core import JudgmentMemoryEngine


class AutonomyTier(str, Enum):
    RED = "red"
    AMBER = "amber"
    GREEN = "green"
    AUTONOMOUS = "autonomous"


@dataclass(frozen=True)
class TierStatus:
    tier: AutonomyTier
    category: str
    verified_count: int
    accuracy: float | None
    conservation_gate_pass: bool
    conservation_reason: str | None
    next_tier: AutonomyTier | None
    next_tier_requirements: str | None
    recommended_action_policy: str


def compute_tier(category: str, verified_count: int, accuracy: float | None,
                 conservation_gate_pass: bool,
                 autonomous_accuracy_min: float = .85) -> AutonomyTier:
    """Choose the highest tier justified by verified evidence."""
    if not conservation_gate_pass:
        return AutonomyTier.RED
    if (not category.strip() or verified_count < 0 or not .85 <= autonomous_accuracy_min <= 1
            or (accuracy is not None and (not isfinite(accuracy) or not 0 <= accuracy <= 1))):
        raise ValueError("Invalid category, verified count, or accuracy")
    if accuracy is None or verified_count < 30:
        return AutonomyTier.RED
    if verified_count >= 200 and accuracy >= autonomous_accuracy_min:
        return AutonomyTier.AUTONOMOUS
    if verified_count >= 100 and accuracy >= .80:
        return AutonomyTier.GREEN
    return AutonomyTier.AMBER


def action_policy(tier: AutonomyTier) -> str:
    return {
        AutonomyTier.RED: "human_review",
        AutonomyTier.AMBER: "confirm",
        AutonomyTier.GREEN: "confirm",
        AutonomyTier.AUTONOMOUS: "auto_accept",
    }[tier]


def check_demotion(current_tier: AutonomyTier, rolling_accuracy: float,
                   conservation_gate_pass: bool) -> AutonomyTier:
    """Apply each demotion threshold, cascading when both are breached."""
    if not isfinite(rolling_accuracy) or not 0 <= rolling_accuracy <= 1:
        raise ValueError("rolling_accuracy must be finite in [0, 1]")
    if not conservation_gate_pass:
        return AutonomyTier.RED
    if current_tier is AutonomyTier.AUTONOMOUS and rolling_accuracy < .83:
        current_tier = AutonomyTier.GREEN
    if current_tier is AutonomyTier.GREEN and rolling_accuracy < .75:
        return AutonomyTier.AMBER
    return current_tier


def compute_tier_status(category: str, verified_count: int, accuracy: float | None,
                        conservation_gate_pass: bool,
                        conservation_reason: str | None = None,
                        autonomous_accuracy_min: float = .85) -> TierStatus:
    tier = compute_tier(category, verified_count, accuracy, conservation_gate_pass,
                        autonomous_accuracy_min)
    next_steps = {
        AutonomyTier.RED: (AutonomyTier.AMBER, "Need 30 verified"),
        AutonomyTier.AMBER: (AutonomyTier.GREEN, "Need 80% accuracy and 100 verified"),
        AutonomyTier.GREEN: (AutonomyTier.AUTONOMOUS,
                             f"Need {autonomous_accuracy_min:.0%} accuracy and 200 verified"),
        AutonomyTier.AUTONOMOUS: (None, None),
    }
    next_tier, requirements = next_steps[tier]
    return TierStatus(tier, category, verified_count, accuracy, conservation_gate_pass,
                      conservation_reason, next_tier, requirements, action_policy(tier))


def evaluate_domain(engine: JudgmentMemoryEngine,
                    label_log_stats: dict[str, dict]) -> dict[str, TierStatus]:
    """Evaluate every category, including those without verified labels."""
    overall_gate, overall_reason = engine.conservation.check_gate(engine.config.n_categories)
    statuses: dict[str, TierStatus] = {}
    for category in engine.config.categories:
        stats = label_log_stats.get(category, {})
        count = int(stats.get("verified_count", 0))
        observed = stats.get("accuracy")
        accuracy = float(observed) if count and observed is not None else None
        rolling = stats.get("rolling_accuracy", accuracy)
        gate_pass = bool(stats.get("conservation_gate_pass", overall_gate))
        reason = stats.get("conservation_reason", overall_reason if not gate_pass else None)
        minimum = float(stats.get("autonomous_accuracy_min", .85))
        status = compute_tier_status(category, count, accuracy, gate_pass, reason, minimum)
        tier = status.tier if rolling is None else check_demotion(status.tier, float(rolling), gate_pass)
        if tier is not status.tier:
            next_tier = {AutonomyTier.RED: AutonomyTier.AMBER,
                         AutonomyTier.AMBER: AutonomyTier.GREEN,
                         AutonomyTier.GREEN: AutonomyTier.AUTONOMOUS}.get(tier)
            requirements = {
                AutonomyTier.RED: "Need 30 verified",
                AutonomyTier.AMBER: "Need 80% accuracy and 100 verified",
                AutonomyTier.GREEN: f"Need {minimum:.0%} accuracy and 200 verified",
            }.get(tier)
            status = TierStatus(tier, category, count, accuracy, gate_pass, reason,
                                next_tier, requirements, action_policy(tier))
        statuses[category] = status
    return statuses
