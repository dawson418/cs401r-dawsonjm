"""Pandas port of the Lab 2 Glue feature job (glue-scripts/feature_engineer.py).

Windows are measured backwards from snapshot_date T (never today()):
    N-day window  =  purchase_date > T - N days   AND   purchase_date <= T
Null strategy: customers with no transactions get recency 999 and zeros for
counts/spend/ratios; every output feature is NaN-free.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NO_TXN_RECENCY = 999
N_CATEGORIES = 8  # product categories in the Lab 2 catalog


def _prep(transactions: pd.DataFrame, snapshot_date) -> pd.DataFrame:
    t = transactions.copy()
    t["purchase_date"] = pd.to_datetime(t["purchase_date"])
    return t[t["purchase_date"] <= pd.Timestamp(snapshot_date)]  # no post-cutoff leakage


def _window(t: pd.DataFrame, snapshot_date, days: int) -> pd.DataFrame:
    T = pd.Timestamp(snapshot_date)
    return t[t["purchase_date"] > T - pd.Timedelta(days=days)]


def _ids(transactions, customer_ids):
    if customer_ids is not None:
        s = customer_ids["customer_id"] if isinstance(customer_ids, pd.DataFrame) else pd.Series(customer_ids)
    else:
        s = transactions["customer_id"]
    return pd.DataFrame({"customer_id": s.drop_duplicates().to_numpy()})


def compute_recency_features(transactions, snapshot_date, customer_ids=None) -> pd.DataFrame:
    t = _prep(transactions, snapshot_date)
    T = pd.Timestamp(snapshot_date)
    last = t.groupby("customer_id")["purchase_date"].max()
    days = ((T - last).dt.days).clip(lower=0)
    out = _ids(transactions, customer_ids)
    out["days_since_last_purchase"] = out["customer_id"].map(days).fillna(NO_TXN_RECENCY).astype(int)
    return out


def compute_frequency_features(transactions, snapshot_date, customer_ids=None) -> pd.DataFrame:
    t = _prep(transactions, snapshot_date)
    out = _ids(transactions, customer_ids)
    for n in (30, 90, 180):
        c = _window(t, snapshot_date, n).groupby("customer_id").size()
        out[f"purchase_frequency_{n}d"] = out["customer_id"].map(c).fillna(0).astype(int)
    return out


def compute_monetary_features(transactions, snapshot_date, customer_ids=None) -> pd.DataFrame:
    t = _prep(transactions, snapshot_date)
    out = _ids(transactions, customer_ids)
    w90, w180 = _window(t, snapshot_date, 90), _window(t, snapshot_date, 180)
    g180 = w180.groupby("customer_id")
    out["avg_basket_size_6m"] = out["customer_id"].map(g180["num_items"].sum() / g180.size()).fillna(0.0)
    out["total_spend_90d"] = out["customer_id"].map(w90.groupby("customer_id")["order_value"].sum()).fillna(0.0)
    out["avg_order_value"] = out["customer_id"].map(t.groupby("customer_id")["order_value"].mean()).fillna(0.0)
    out["total_lifetime_value"] = out["customer_id"].map(t.groupby("customer_id")["order_value"].sum()).fillna(0.0)
    return out


def compute_behavioral_features(transactions, customer_ids=None) -> pd.DataFrame:
    t = transactions
    out = _ids(transactions, customer_ids)
    div = t.groupby("customer_id")["product_category"].nunique() / N_CATEGORIES
    out["category_diversity_score"] = out["customer_id"].map(div).fillna(0.0).clip(0, 1)
    online = t[t["channel"] == "online"].groupby("customer_id").size()
    store = t[t["channel"] != "online"].groupby("customer_id").size()
    o = out["customer_id"].map(online).fillna(0)
    s = out["customer_id"].map(store).fillna(0)
    out["online_to_store_ratio"] = (o / s.where(s > 0, 1)).astype(float)  # store==0 -> ratio = online count
    return out


def build_churn_feature_set(customers: pd.DataFrame, transactions: pd.DataFrame, snapshot_date) -> pd.DataFrame:
    ids = customers[["customer_id"]]
    parts = [
        compute_recency_features(transactions, snapshot_date, ids),
        compute_frequency_features(transactions, snapshot_date, ids),
        compute_monetary_features(transactions, snapshot_date, ids),
        compute_behavioral_features(transactions, ids),
    ]
    feats = parts[0]
    for p in parts[1:]:
        feats = feats.merge(p, on="customer_id", how="left")

    t = _prep(transactions, snapshot_date)
    T = pd.Timestamp(snapshot_date)
    if "signup_date" in customers.columns:
        start = pd.to_datetime(customers.set_index("customer_id")["signup_date"])
    else:  # fall back to first purchase when the roster has no signup date
        start = t.groupby("customer_id")["purchase_date"].min()
    tenure = (T - start).dt.days.clip(lower=0)
    feats["customer_tenure_days"] = feats["customer_id"].map(tenure).fillna(0).astype(int)

    extra = [c for c in customers.columns if c not in feats.columns]
    feats = customers[["customer_id"] + extra].merge(feats, on="customer_id", how="left")
    num = feats.select_dtypes("number").columns
    feats[num] = feats[num].fillna(0)
    return feats
