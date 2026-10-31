"""NorthStar churn model packaged for the Lab 4 pipeline (CS 401R Lab 4).

Contract with train_sagemaker.py:
    FEATURE_COLUMNS, LABEL, train(df, seed=42) -> (xgboost.Booster, metrics dict)
Runs inside the SageMaker XGBoost 1.7-1 container: only numpy/pandas/sklearn/
xgboost/boto3 are available. No mlflow, no sagemaker imports here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

FEATURE_COLUMNS = [
    "days_since_last_purchase",
    "customer_tenure_days",
    "purchase_frequency_30d",
    "purchase_frequency_90d",
    "purchase_frequency_180d",
    "avg_order_value",
    "total_spend_90d",
    "total_lifetime_value",
    "avg_basket_size_6m",
    "category_diversity_score",
    "online_to_store_ratio",
]
LABEL = "churn_label"
TIER_COLUMN = "loyalty_tier"

# Same gates as Lab 3 / tests/test_model.py
MIN_PRECISION_TOP10 = 0.50
MIN_RECALL_TOP10 = 0.25

PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "auc",
    "max_depth": 4,
    "eta": 0.08,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,
    "seed": 42,
    "nthread": 2,
}


def _monotone_constraints():
    """Churn risk must never fall as days_since_last_purchase grows (tests/test_model.py
    checks this). Enforce it in the model instead of hoping the data cooperates."""
    return "(" + ",".join("1" if c == "days_since_last_purchase" else "0" for c in FEATURE_COLUMNS) + ")"

NUM_ROUNDS = 300


def _top_k_metrics(y_true: np.ndarray, scores: np.ndarray, frac: float = 0.10):
    k = max(1, int(round(len(scores) * frac)))
    order = np.argsort(-scores, kind="stable")[:k]
    hits = float(y_true[order].sum())
    total_pos = float(y_true.sum())
    return hits / k, (hits / total_pos if total_pos else 0.0)


def _bootstrap_lift_ci(y, p_model, p_base, n_boot=500, seed=42):
    """95% bootstrap CI on AUC(model) - AUC(recency-only baseline)."""
    rng = np.random.default_rng(seed)
    n = len(y)
    lifts = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        yb = y[idx]
        if yb.min() == yb.max():
            continue
        lifts.append(roc_auc_score(yb, p_model[idx]) - roc_auc_score(yb, p_base[idx]))
    lo, hi = np.percentile(lifts, [2.5, 97.5])
    return float(lo), float(hi)


def train(df: pd.DataFrame, seed: int = 42):
    df = df.copy()
    if TIER_COLUMN not in df.columns:
        df[TIER_COLUMN] = "unknown"
    X = df[FEATURE_COLUMNS].astype(float)
    y = df[LABEL].astype(int)
    tiers = df[TIER_COLUMN].astype(str)

    X_tr, X_val, y_tr, y_val, _t_tr, t_val = train_test_split(
        X, y, tiers, test_size=0.30, random_state=seed, stratify=y)

    params = dict(PARAMS, seed=seed, monotone_constraints=_monotone_constraints())
    dtr = xgb.DMatrix(X_tr, label=y_tr, feature_names=FEATURE_COLUMNS)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_COLUMNS)
    booster = xgb.train(params, dtr, num_boost_round=NUM_ROUNDS)

    p_model = booster.predict(dval)
    yv = y_val.to_numpy()

    # Recency-only baseline (logistic regression on days_since_last_purchase)
    rec = ["days_since_last_purchase"]
    med = X_tr[rec].median()
    base = LogisticRegression(max_iter=1000).fit(X_tr[rec].fillna(med), y_tr)
    p_base = base.predict_proba(X_val[rec].fillna(med))[:, 1]

    auc = float(roc_auc_score(yv, p_model))
    base_auc = float(roc_auc_score(yv, p_base))
    lo, hi = _bootstrap_lift_ci(yv, p_model, p_base, seed=seed)
    prec, rec10 = _top_k_metrics(yv, p_model)

    metrics = {
        "auc_roc": auc,
        "baseline_auc_roc": base_auc,
        "auc_lift_over_baseline": auc - base_auc,
        "auc_lift_ci_low": lo,
        "auc_lift_ci_high": hi,
        "precision_top10": float(prec),
        "recall_top10": float(rec10),
        "positive_rate_val": float(yv.mean()),
        "n_train": int(len(X_tr)),
        "n_val": int(len(X_val)),
        "seed": int(seed),
    }

    # Per-tier slices (used by tests/test_fairness.py): top-10% recall per tier
    # using each tier's own top-10% by score is NOT what ops does; use the
    # global threshold so tiers are compared on the same decision rule.
    k = max(1, int(round(len(p_model) * 0.10)))
    thresh = np.sort(p_model)[::-1][k - 1]
    flagged = p_model >= thresh
    for tier in sorted(t_val.unique()):
        m = (t_val == tier).to_numpy()
        pos = float(yv[m].sum())
        key = str(tier).lower().replace(" ", "_")
        metrics[f"positives_tier_{key}"] = int(pos)
        metrics[f"n_tier_{key}"] = int(m.sum())
        metrics[f"recall_tier_{key}"] = float((flagged & m & (yv == 1)).sum() / pos) if pos else 0.0

    # Keep Lab 3's behaviour: a model that misses a gate fails the training step
    # and is therefore never registered.
    failures = []
    if prec < MIN_PRECISION_TOP10:
        failures.append(f"precision_top10 {prec:.3f} < {MIN_PRECISION_TOP10}")
    if rec10 < MIN_RECALL_TOP10:
        failures.append(f"recall_top10 {rec10:.3f} < {MIN_RECALL_TOP10}")
    if lo <= 0:
        failures.append(f"lift CI low {lo:.4f} <= 0 (not distinguishable from baseline)")
    if failures:
        raise RuntimeError("Model failed quality gate: " + "; ".join(failures))

    return booster, metrics
