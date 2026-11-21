"""CSV validation and ephemeral engine configuration."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd
from jm_core import DomainConfig

_RESERVED = {"label_id", "category", "verified_outcome", "annotator_id", "action", "timestamp",
             "proposed_action", "actual_action", "verified", "existing_label"}

@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]
    warnings: list[str]
    stats: dict[str, int]


def factor_columns(df: pd.DataFrame) -> list[str]:
    return [str(col) for col in df.columns if col not in _RESERVED
            and pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_bool_dtype(df[col])]


def normalize_csv(df: pd.DataFrame) -> pd.DataFrame:
    """Adapt v6 uploads to the internal replay schema without changing legacy uploads."""
    v6_fields = {"proposed_action", "actual_action", "verified"}
    if not v6_fields.intersection(df.columns):
        return df
    if not v6_fields.issubset(df.columns) or "verified_outcome" in df.columns or "action" in df.columns:
        raise ValueError("Use either the v6 action/verified columns or legacy action/verified_outcome columns")
    verified = df["verified"].map(lambda value: str(value).lower())
    if not all(value in ("true", "false") for value in verified):
        raise ValueError("verified must contain only true or false")
    if (verified.eq("true") & df["actual_action"].isna()).any():
        raise ValueError("Verified rows require actual_action")
    if (verified.eq("false") & df["actual_action"].notna()).any():
        raise ValueError("Unverified rows must not have actual_action")
    result = df.copy()
    result["verified_outcome"] = (result["proposed_action"] == result["actual_action"]).where(verified.eq("true"))
    result["action"] = result["actual_action"]
    rename = {name: name[7:] for name in factor_columns(result) if name.startswith("factor_")}
    if len(set(rename.values())) != len(rename) or any(target in result.columns for target in rename.values()):
        raise ValueError("Factor names collide after removing factor_ prefix")
    return result.rename(columns=rename)


def validate_csv(df: pd.DataFrame) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    required = {"label_id", "category", "verified_outcome"}
    missing = required - set(df.columns)
    if missing: errors.append("Missing required columns: " + ", ".join(sorted(missing)))
    if df.columns.duplicated().any() or any(not str(name).strip() for name in df.columns):
        errors.append("CSV headers must be unique and nonempty")
    if len(df) < 200: errors.append("At least 200 rows are required")
    factors = factor_columns(df)
    if len(factors) < 2: errors.append("At least 2 numeric factor columns are required")
    for name in factors:
        values = pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            errors.append(f"Factor {name} must be finite and in [0, 1]")
    verified_count = 0
    if "verified_outcome" in df:
        observed = df["verified_outcome"].dropna()
        verified_count = len(observed)
        if not observed.isin([True, False, 0, 1]).all():
            errors.append("verified_outcome must be boolean or 0/1")
        if verified_count < 50: warnings.append("Fewer than 50 verified outcomes; inversion detection may be unavailable")
    if "action" in df:
        if any("|" in str(value) for value in df["action"].dropna()):
            errors.append("Action names cannot contain |")
    if "proposed_action" in df and df["proposed_action"].isna().any():
        errors.append("proposed_action must be present")
    if "action" in df:
        vocabulary = set(df["action"].dropna().astype(str))
        if "proposed_action" in df:
            vocabulary |= set(df["proposed_action"].dropna().astype(str))
        if len(vocabulary) > 10:
            errors.append("CSV must contain 2 to 10 actions")
        if any(not action.strip() or "|" in action for action in vocabulary):
            errors.append("Action names must be nonempty and cannot contain |")
    if "label_id" in df and (df["label_id"].isna().any() or df["label_id"].astype(str).duplicated().any()):
        errors.append("label_id must be present and unique")
    if "category" in df:
        if df["category"].isna().any() or any(not str(value).strip() for value in df["category"].dropna()):
            errors.append("category must be nonempty")
        for category, count in df["category"].value_counts().items():
            if count < 10: warnings.append(f"Category {category} has fewer than 10 rows")
        if not 1 <= df["category"].nunique() <= 20:
            errors.append("CSV must contain 1 to 20 categories")
        if any("|" in str(value) for value in df["category"].dropna()):
            errors.append("Category names cannot contain |")
    stats = {"row_count": len(df), "category_count": int(df["category"].nunique()) if "category" in df else 0,
             "factor_count": len(factors), "verified_count": verified_count,
             "annotator_count": int(df["annotator_id"].nunique()) if "annotator_id" in df else 0}
    return ValidationResult(not errors, errors, warnings, stats)


def infer_config(df: pd.DataFrame) -> DomainConfig:
    factors = factor_columns(df)
    categories = [str(value) for value in df["category"].dropna().unique()]
    actions: list[str] = []
    for column in ("proposed_action", "action"):
        if column in df:
            actions.extend(str(value) for value in df[column].dropna().unique() if str(value).strip())
    actions = list(dict.fromkeys(actions))
    if not actions:
        actions = ["approve", "reject"]
    elif len(actions) == 1:
        actions.append("reject" if actions[0] != "reject" else "approve")
    return DomainConfig("label_health_ephemeral", "Label Health Report", factors, categories, actions)
