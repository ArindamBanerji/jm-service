"""Ephemeral analysis of uploaded labels."""
from __future__ import annotations
from time import perf_counter
from typing import Any
import pandas as pd
from jm_core import ConservationState, DomainConfig, JudgmentMemoryEngine


def run_analysis(df: pd.DataFrame, config: DomainConfig) -> dict[str, Any]:
    start = perf_counter()
    engine = JudgmentMemoryEngine(config)
    warnings: list[str] = []
    ordered = df
    if "timestamp" in df:
        timestamps = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        if timestamps.notna().all():
            ordered = df.assign(_sort_time=timestamps).sort_values("_sort_time", kind="stable").drop(columns="_sort_time")
        else:
            warnings.append("Invalid timestamp; CSV row order used")
    if "action" in df:
        unknown = set(df["action"].dropna().astype(str)) - set(config.actions)
        if unknown:
            raise ValueError(f"Unknown action values: {sorted(unknown)}")
    verified = ordered[ordered["verified_outcome"].notna()]
    for _, row in verified.iterrows():
        factors = {name: float(row[name]) for name in config.factors}
        category = str(row["category"])
        score = engine.score(factors, category)
        correct = bool(row["verified_outcome"])
        action = str(row["action"]) if "action" in df and pd.notna(row["action"]) else config.actions[0 if correct else 1]
        engine.learn(score.decision_id, action, confirmed=score.recommended_action == action,
                     outcome_correct=correct, track_outcome=True)
    items = [{"factors": {name: float(row[name]) for name in config.factors},
              "category": str(row["category"])} for _, row in ordered.iterrows()]
    scored = engine.score_readonly_batch(items)
    needs_reverification = sum(max(scores.values()) < 0.5 for scores in scored)
    categories: list[dict[str, Any]] = []
    silent: list[dict[str, Any]] = []
    for category in config.categories:
        rows = verified[verified["category"].astype(str) == category]
        count = len(rows)
        accuracy = float(rows["verified_outcome"].astype(float).mean()) if count else None
        risk = "RED" if count < 30 or (accuracy is not None and accuracy < 0.6) else "AMBER" if accuracy is not None and (accuracy < 0.8 or count < 100) else "GREEN"
        category_gate = ConservationState()
        for outcome in rows["verified_outcome"]:
            category_gate.update(bool(outcome), category)
        gate_pass, gate_reason = category_gate.check_gate(1)
        phase = "warmup" if gate_reason == "warmup" else "clear" if gate_pass else "paused"
        entry = {"category": category, "accuracy": accuracy, "verified_count": count,
                 "risk_level": risk, "conservation_phase": phase,
                 "conservation_alpha": 1.0 if count else 0.0,
                 "conservation_q": category_gate.rolling_accuracy}
        categories.append(entry)
        if count < 30: silent.append({"category": category, "verified_count": count, "accuracy": accuracy})
    profiles: list[dict[str, Any]] | None = None
    if "annotator_id" in df:
        profiles = []
        for annotator, rows in verified.groupby("annotator_id"):
            per_category = {str(cat): float(group["verified_outcome"].astype(float).mean())
                            for cat, group in rows.groupby("category")}
            profiles.append({"annotator_id": str(annotator), "total_labels": len(rows),
                             "overall_accuracy": float(rows["verified_outcome"].astype(float).mean()),
                             "category_accuracy": per_category,
                             "strongest": max(per_category, key=per_category.get) if per_category else None,  # type: ignore[arg-type]
                             "weakest": min(per_category, key=per_category.get) if per_category else None})  # type: ignore[arg-type]
    overall = float(verified["verified_outcome"].astype(float).mean()) if len(verified) else None
    inversion = engine.signal_confidence_inversion()
    cost = {"current_error_rate": 1 - overall, "projected_volume": 10000,
            "cost_per_error": 25.0, "total_projected_cost": round((1 - overall) * 10000 * 25.0, 2),
            "labels_needing_reverification": needs_reverification,
            "confidence": "low confidence" if len(verified) < 50 else "standard"} if overall is not None else None
    return {"report_version": "1.0", "metadata": {"row_count": len(df), "category_count": len(config.categories),
                         "factor_count": len(config.factors), "verified_count": len(verified),
                         "analysis_time_ms": round((perf_counter() - start) * 1000, 2)},
            "overall_accuracy": overall, "category_risks": categories, "inversion": inversion,
            "annotator_profiles": profiles, "silent_risks": silent, "cost_projection": cost,
            "factor_names": list(config.factors), "warnings": warnings,
            "message": "No verified labels found. Upload labeled data with ground truth to see accuracy and cost projections." if overall is None else None}
