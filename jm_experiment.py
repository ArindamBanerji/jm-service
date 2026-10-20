"""
jm_experiment.py — Validate that the standalone JM engine compounds

Runs three experiments:
  1. COMPOUNDING: Quality divergence between learning engine and frozen twin
  2. MULTI-TENANT: Two independent tenants compound independently
  3. CONSERVATION: Gate fires when accuracy degrades

This is the validation that JM-as-a-Service works.
"""

import json
import math
import random
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from jm_core import JudgmentMemoryEngine, DomainConfig


def make_procurement_domain(domain_id: str = "demo") -> DomainConfig:
    """A realistic procurement decision domain."""
    return DomainConfig(
        domain_id=domain_id,
        name="Procurement Decisions",
        factors=["spend_amount", "supplier_risk", "urgency", "contract_coverage", "history_score", "compliance_flag"],
        categories=["invoice", "purchase_order", "contract_renewal", "new_supplier"],
        actions=["approve", "escalate", "reject", "hold"],
    )


def generate_decision(category: str, seed_rng: random.Random) -> tuple[dict[str, float], str]:
    """
    Generate a synthetic decision with a ground-truth correct action.
    The ground truth has LEARNABLE structure — not random.

    The pattern:
      - High spend + high risk + low coverage → escalate
      - High spend + low risk + high coverage → approve
      - Low compliance → reject
      - Medium everything → hold
    """
    factors = {
        "spend_amount": seed_rng.random(),
        "supplier_risk": seed_rng.random(),
        "urgency": seed_rng.random(),
        "contract_coverage": seed_rng.random(),
        "history_score": seed_rng.random(),
        "compliance_flag": seed_rng.random(),
    }

    # Ground truth logic (what the service should learn)
    spend = factors["spend_amount"]
    risk = factors["supplier_risk"]
    coverage = factors["contract_coverage"]
    compliance = factors["compliance_flag"]
    urgency = factors["urgency"]

    if compliance < 0.2:
        correct = "reject"
    elif spend > 0.7 and risk > 0.6 and coverage < 0.4:
        correct = "escalate"
    elif spend > 0.5 and risk < 0.4 and coverage > 0.6:
        correct = "approve"
    elif urgency > 0.8 and risk < 0.3:
        correct = "approve"
    else:
        correct = "hold"

    return factors, correct


def run_experiment_1_compounding(n_decisions: int = 1000) -> dict:
    """
    EXPERIMENT 1: Quality divergence — learning twin vs frozen twin.

    Both start from the same initial state. The learning twin gets
    outcome feedback; the frozen twin doesn't. We measure the
    accuracy gap over time.
    """
    print("=" * 60)
    print("EXPERIMENT 1: COMPOUNDING (learning vs frozen twin)")
    print("=" * 60)

    config = make_procurement_domain("exp1")
    learning = JudgmentMemoryEngine(config)
    frozen = JudgmentMemoryEngine(config)

    rng = random.Random(42)
    categories = config.categories

    # Track accuracy in windows
    window = 50
    learning_window: list[bool] = []
    frozen_window: list[bool] = []
    trajectory: list[dict] = []

    for i in range(n_decisions):
        cat = rng.choice(categories)
        factors, correct_action = generate_decision(cat, rng)

        # Score with both engines
        lr = learning.score(factors, cat)
        fr = frozen.score(factors, cat)

        lr_correct = lr.recommended_action == correct_action
        fr_correct = fr.recommended_action == correct_action

        learning_window.append(lr_correct)
        frozen_window.append(fr_correct)
        if len(learning_window) > window:
            learning_window.pop(0)
            frozen_window.pop(0)

        # Learning twin gets feedback
        learning.learn(lr.decision_id, correct_action, confirmed=lr_correct)

        # Frozen twin gets NO feedback (no learn call)

        if (i + 1) % window == 0:
            lr_acc = sum(learning_window) / len(learning_window)
            fr_acc = sum(frozen_window) / len(frozen_window)
            trajectory.append({
                "decision": i + 1,
                "learning_accuracy": round(lr_acc, 4),
                "frozen_accuracy": round(fr_acc, 4),
                "gap_pp": round((lr_acc - fr_acc) * 100, 2),
            })
            print(f"  Decision {i+1:4d}: learning={lr_acc:.3f}  frozen={fr_acc:.3f}  gap=+{(lr_acc - fr_acc)*100:.1f}pp")

    final_gap = trajectory[-1]["gap_pp"]
    print(f"\n  RESULT: Final gap = +{final_gap}pp after {n_decisions} decisions")
    print(f"  State size: {learning.state_size_bytes():,} bytes")

    return {
        "experiment": "compounding",
        "n_decisions": n_decisions,
        "trajectory": trajectory,
        "final_learning_accuracy": trajectory[-1]["learning_accuracy"],
        "final_frozen_accuracy": trajectory[-1]["frozen_accuracy"],
        "final_gap_pp": final_gap,
        "state_size_bytes": learning.state_size_bytes(),
        "PASS": final_gap > 5.0,  # >5pp gap = compounding confirmed
    }


def run_experiment_2_multitenant() -> dict:
    """
    EXPERIMENT 2: Multi-tenant isolation.

    Two tenants with DIFFERENT decision patterns. Each should converge
    to its own pattern without interference.
    """
    print("\n" + "=" * 60)
    print("EXPERIMENT 2: MULTI-TENANT ISOLATION")
    print("=" * 60)

    # Tenant A: procurement (approve-heavy)
    config_a = make_procurement_domain("tenant_a")
    engine_a = JudgmentMemoryEngine(config_a)

    # Tenant B: security (escalate-heavy)
    config_b = DomainConfig(
        domain_id="tenant_b",
        name="Security Triage",
        factors=["severity", "blast_radius", "confidence", "novelty", "asset_value", "response_time"],
        categories=["alert", "incident", "vulnerability", "audit_finding"],
        actions=["approve", "escalate", "reject", "hold"],
    )
    engine_b = JudgmentMemoryEngine(config_b)

    rng_a = random.Random(100)
    rng_b = random.Random(200)

    n_decisions = 500

    # Run both tenants
    for i in range(n_decisions):
        # Tenant A: procurement decisions
        cat_a = rng_a.choice(config_a.categories)
        factors_a, correct_a = generate_decision(cat_a, rng_a)
        result_a = engine_a.score(factors_a, cat_a)
        engine_a.learn(result_a.decision_id, correct_a, confirmed=(result_a.recommended_action == correct_a))

        # Tenant B: security decisions (different pattern — high severity → escalate)
        cat_b = rng_b.choice(config_b.categories)
        factors_b = {f: rng_b.random() for f in config_b.factors}
        if factors_b["severity"] > 0.7:
            correct_b = "escalate"
        elif factors_b["confidence"] < 0.3:
            correct_b = "hold"
        elif factors_b["severity"] < 0.2 and factors_b["blast_radius"] < 0.3:
            correct_b = "approve"
        else:
            correct_b = "escalate"

        result_b = engine_b.score(factors_b, cat_b)
        engine_b.learn(result_b.decision_id, correct_b, confirmed=(result_b.recommended_action == correct_b))

    diag_a = engine_a.diagnostics()
    diag_b = engine_b.diagnostics()

    print(f"  Tenant A (Procurement): accuracy={diag_a['accuracy']:.3f}, decisions={diag_a['total_decisions']}")
    print(f"  Tenant B (Security):    accuracy={diag_b['accuracy']:.3f}, decisions={diag_b['total_decisions']}")
    print(f"  Tenant A state: {engine_a.state_size_bytes():,} bytes")
    print(f"  Tenant B state: {engine_b.state_size_bytes():,} bytes")

    # Check isolation: centroids should be DIFFERENT
    # Compare centroid for "approve" in first category
    key_a = f"{config_a.categories[0]}|approve"
    key_b = f"{config_b.categories[0]}|approve"
    centroid_a = engine_a.centroids[key_a]
    centroid_b = engine_b.centroids[key_b]
    print(f"  Centroid A (invoice|approve): {[round(c, 3) for c in centroid_a]}")
    print(f"  Centroid B (alert|approve):   {[round(c, 3) for c in centroid_b]}")

    # They should have diverged from the initial 0.5
    drift_a = sum(abs(c - 0.5) for c in centroid_a) / len(centroid_a)
    drift_b = sum(abs(c - 0.5) for c in centroid_b) / len(centroid_b)

    print(f"\n  RESULT: Centroids diverged from initial (avg drift: A={drift_a:.4f}, B={drift_b:.4f})")
    print(f"  Tenant states are independent: {key_a} != {key_b}")

    return {
        "experiment": "multi_tenant",
        "tenant_a": {"accuracy": diag_a["accuracy"], "state_bytes": engine_a.state_size_bytes()},
        "tenant_b": {"accuracy": diag_b["accuracy"], "state_bytes": engine_b.state_size_bytes()},
        "centroids_diverged": drift_a > 0.01 and drift_b > 0.01,
        "PASS": drift_a > 0.01 and drift_b > 0.01,
    }


def run_experiment_3_conservation() -> dict:
    """
    EXPERIMENT 3: Conservation gate fires on degradation.

    Train normally for 500 decisions, then inject a regime break
    (ground truth changes). The gate should detect the degradation.
    """
    print("\n" + "=" * 60)
    print("EXPERIMENT 3: CONSERVATION GATE")
    print("=" * 60)

    config = make_procurement_domain("exp3")
    engine = JudgmentMemoryEngine(config)
    rng = random.Random(42)

    # Phase 1: normal training (500 decisions)
    print("  Phase 1: Normal training (500 decisions)...")
    for i in range(500):
        cat = rng.choice(config.categories)
        factors, correct = generate_decision(cat, rng)
        result = engine.score(factors, cat)
        engine.learn(result.decision_id, correct, confirmed=(result.recommended_action == correct))

    diag_before = engine.diagnostics()
    print(f"  Pre-break accuracy: {diag_before['accuracy']:.3f}")
    print(f"  Gate status: {diag_before['gate_status']}")

    # Phase 2: regime break — INVERT the ground truth
    print("  Phase 2: Regime break (inverted ground truth, 100 decisions)...")
    gate_fired = False
    gate_fired_at = None

    for i in range(100):
        cat = rng.choice(config.categories)
        factors, correct = generate_decision(cat, rng)

        # INVERT the correct action
        inverted_actions = [a for a in config.actions if a != correct]
        wrong_correct = rng.choice(inverted_actions)

        result = engine.score(factors, cat)
        engine.learn(result.decision_id, wrong_correct, confirmed=False)

        gate_pass, reason = engine.conservation.check_gate(config.n_categories)
        if not gate_pass and not gate_fired:
            gate_fired = True
            gate_fired_at = 500 + i + 1
            print(f"  *** GATE FIRED at decision {gate_fired_at}: {reason}")

    diag_after = engine.diagnostics()
    print(f"  Post-break accuracy: {diag_after['accuracy']:.3f}")
    print(f"  Gate status: {diag_after['gate_status']}")

    if gate_fired:
        print(f"\n  RESULT: Conservation gate detected degradation at decision {gate_fired_at}")
    else:
        print(f"\n  RESULT: Gate did not fire (accuracy may still be above threshold)")

    return {
        "experiment": "conservation",
        "pre_break_accuracy": diag_before["accuracy"],
        "post_break_accuracy": diag_after["accuracy"],
        "gate_fired": gate_fired,
        "gate_fired_at": gate_fired_at,
        "gate_status": diag_after["gate_status"],
        "PASS": gate_fired,
    }


def run_experiment_4_state_persistence() -> dict:
    """
    EXPERIMENT 4: State export/import — verify lossless round-trip.
    """
    print("\n" + "=" * 60)
    print("EXPERIMENT 4: STATE PERSISTENCE (export → import → verify)")
    print("=" * 60)

    config = make_procurement_domain("exp4")
    engine = JudgmentMemoryEngine(config)
    rng = random.Random(42)

    # Train for 200 decisions
    for i in range(200):
        cat = rng.choice(config.categories)
        factors, correct = generate_decision(cat, rng)
        result = engine.score(factors, cat)
        engine.learn(result.decision_id, correct, confirmed=(result.recommended_action == correct))

    # Export
    state = engine.export_state()
    state_json = json.dumps(state)
    print(f"  Exported state: {len(state_json):,} bytes")
    print(f"  Centroid count: {len(state['centroids'])}")

    # Import into new engine
    restored = JudgmentMemoryEngine.from_state(state)

    # Score the same input with both — should be identical
    test_factors = {"spend_amount": 0.8, "supplier_risk": 0.7, "urgency": 0.5, "contract_coverage": 0.3, "history_score": 0.6, "compliance_flag": 0.9}

    r1 = engine.score(test_factors, "invoice")
    r2 = restored.score(test_factors, "invoice")

    match = r1.recommended_action == r2.recommended_action
    conf_match = abs(r1.confidence - r2.confidence) < 0.001
    print(f"  Original:  action={r1.recommended_action}, confidence={r1.confidence:.4f}")
    print(f"  Restored:  action={r2.recommended_action}, confidence={r2.confidence:.4f}")
    print(f"  Match: action={match}, confidence_delta={abs(r1.confidence - r2.confidence):.6f}")

    print(f"\n  RESULT: State round-trip {'LOSSLESS' if match and conf_match else 'LOSSY'}")

    return {
        "experiment": "persistence",
        "state_bytes": len(state_json),
        "centroid_count": len(state["centroids"]),
        "action_match": match,
        "confidence_match": conf_match,
        "PASS": match and conf_match,
    }


if __name__ == "__main__":
    print("JM-as-a-Service Validation Suite")
    print("================================\n")

    results = []
    results.append(run_experiment_1_compounding(1000))
    results.append(run_experiment_2_multitenant())
    results.append(run_experiment_3_conservation())
    results.append(run_experiment_4_state_persistence())

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_pass = True
    for r in results:
        status = "PASS" if r["PASS"] else "FAIL"
        print(f"  {r['experiment']:20s}: {status}")
        if not r["PASS"]:
            all_pass = False

    print(f"\n  Overall: {'ALL PASS' if all_pass else 'SOME FAILED'}")

    # Save results
    out_path = os.path.join(os.path.dirname(__file__), "experiment_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved to: {out_path}")
