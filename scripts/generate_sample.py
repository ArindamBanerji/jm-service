"""Generate the versioned, fictional medical NER demo fixture."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "frontend" / "public" / "demo" / "sample_data.json"
EXAMPLES = {
    "MEDICATION": [
        ("Aspirin", "Aspirin appears in the medication list."),
        ("ibuprofen", "The note lists ibuprofen as a medication."),
        ("metformin", "A medication entry mentions metformin."),
        ("amoxicillin", "The chart includes amoxicillin."),
    ],
    "CONDITION": [
        ("asthma", "The note mentions asthma."),
        ("migraine", "A condition entry lists migraine."),
        ("arthritis", "The chart mentions arthritis."),
        ("anemia", "The note records anemia."),
    ],
    "TEST": [
        ("glucose test", "A glucose test is listed."),
        ("blood count", "The note requests a blood count."),
        ("urinalysis", "The chart lists urinalysis."),
        ("MRI scan", "An MRI scan appears in the test list."),
    ],
}


def generate() -> dict:
    rows = []
    for index in range(500):
        category = ("MEDICATION", "CONDITION", "TEST")[index % 3]
        mention, sentence = EXAMPLES[category][(index // 3) % 4]
        evidence = index % 25
        outcome = None if evidence < 5 else False if evidence < 9 else True
        start = sentence.index(mention)
        rows.append({
            "label_id": f"med-{index + 1:04d}",
            "category": category,
            "annotator_id": f"demo-ann-{index % 4 + 1}",
            "factor_model_confidence": round(0.35 + (index * 37 % 61) / 100, 2),
            "factor_item_difficulty": round(0.08 + (index * 29 % 85) / 100, 2),
            "text": sentence,
            "span": {"start": start, "end": start + len(mention), "label": category},
            "verified_outcome": outcome,
        })
    return {"domain_id": "medical-ner-demo-v1", "rows": rows}


if __name__ == "__main__":
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(json.dumps(generate(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
