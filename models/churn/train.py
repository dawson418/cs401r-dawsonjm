"""
NorthStar Retail — Churn Prediction Training Script (Lab 3, Track A)

Pulls features from the SageMaker Feature Store offline store via Athena,
trains an XGBoost churn model, evaluates it against the recency-only
baseline (paired bootstrap CI), evaluates loyalty-tier slices, logs the run
to a SageMaker MLflow App, and (with --register) registers the model in the
Model Registry as PendingManualApproval.

Experiment tracking needs: pip install mlflow sagemaker-mlflow
Use an MLflow APP (free), never a Tracking Server ($0.60/hr).

Example (graded run):

    python models/churn/train.py \
        --feature-group-name "$FG" --artifacts-bucket "$BUCKET" \
        --mlflow-arn "$MLFLOW_APP_ARN" \
        --max-depth 4 --eta 0.05 --num-round 400 \
        --run-name final-depth4-eta0.05 --register \
        --output-data-dir docs/lab3-evidence 2>&1 | tee docs/lab3-evidence/train-final.log
"""

import argparse
import json
import os
import tarfile
from datetime import datetime, timezone

import boto3
import matplotlib

matplotlib.use("Agg")  # headless: write PNGs, never open a window
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

# sagemaker 3.x REMOVED the feature_store package; pin sagemaker<3.0.0.
try:
    import sagemaker
except ImportError:
    sagemaker = None
    SAGEMAKER_AVAILABLE = False
    print("WARNING: sagemaker not installed — running in local test mode")
else:
    try:
        from sagemaker.feature_store.feature_group import FeatureGroup
        from sagemaker.session import Session

        SAGEMAKER_AVAILABLE = True
    except ImportError:
        SAGEMAKER_AVAILABLE = False
        print("WARNING: sagemaker is installed but has no feature_store module. "
              "This is sagemaker 3.x, which dropped it. Run "
              "`pip install 'sagemaker>=2.200.0,<3.0.0'`.")

import xgboost as xgb  # noqa: E402
from sklearn.metrics import confusion_matrix, roc_auc_score  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

# ── Columns ────────────────────────────────────────────────────────────────────

FEATURE_COLUMNS = [
    # Recency and tenure
    "days_since_last_purchase",
    "customer_tenure_days",
    # Frequency
    "purchase_frequency_30d",
    "purchase_frequency_90d",
    "purchase_frequency_180d",
    # Monetary
    "avg_order_value",
    "total_spend_90d",
    "total_lifetime_value",
    "avg_basket_size_6m",
    # Behavioural
    "category_diversity_score",
    "online_to_store_ratio",
]

# churn_risk_score is a pure recency heuristic. Excluded by default; add it
# with --include-risk-score and report results with AND without it.
BASELINE_COLUMN = "churn_risk_score"
BASELINE_FEATURE = "days_since_last_purchase"
LABEL_COLUMN = "churn_label"
SLICE_COLUMN = "loyalty_tier"  # slice key only, never a model input

# A tier with fewer test positives than this cannot support a claim: AUC from
# a handful of positives swings wildly with the split (see Lab 3 handout).
MIN_SLICE_POSITIVES = 30

EVAL_THRESHOLDS = {
    "precision_top10": 0.50,
    "recall_top10": 0.25,
}
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 42
MODEL_PACKAGE_GROUP = "northstar-churn-models"  # Lab 5 deploys from this name


def get_features(args) -> list:
    """Model input columns for this run."""
    feats = list(FEATURE_COLUMNS)
    if args.include_risk_score:
        feats.append(BASELINE_COLUMN)
    return feats


# ── Argument Parsing ───────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="NorthStar churn prediction training")

    # Data
    p.add_argument("--feature-group-name", type=str,
                   default="northstar-dev-customer-features",
                   help="Lab 2 feature group (terraform output -raw feature_group_name)")
    p.add_argument("--training-start-date", type=str, default="2026-01-01",
                   help="Earliest Lab 2 INGEST date (event_time is ingest time, not T)")
    p.add_argument("--training-end-date", type=str, default="2027-01-01",
                   help="Latest Lab 2 ingest date")
    p.add_argument("--artifacts-bucket", type=str, required=True,
                   help="Lab 1 bucket northstar-dev-data-<account>; writes only under artifacts/")
    p.add_argument("--local-data-path", type=str, default=None,
                   help="DEV ONLY: local feature CSV. The graded run must NOT use this.")

    # XGBoost hyperparameters
    p.add_argument("--max-depth", type=int, default=6)
    p.add_argument("--eta", type=float, default=0.1)
    p.add_argument("--num-round", type=int, default=200)
    p.add_argument("--min-child-weight", type=int, default=5)
    p.add_argument("--subsample", type=float, default=0.8)
    p.add_argument("--colsample-bytree", type=float, default=0.8)
    p.add_argument("--scale-pos-weight", type=float, default=None,
                   help="Leave unset: computed as negatives/positives from the training "
                        "split (~3.5 at 22%% churn).")
    p.add_argument("--include-risk-score", action="store_true",
                   help="Add churn_risk_score (a recency heuristic) as an input feature.")
    p.add_argument("--seed", type=int, default=42,
                   help="Split + XGBoost seed. Keep fixed when comparing hyperparameters.")
    p.add_argument("--early-stopping-fraction", type=float, default=0.15,
                   help="Fraction of the TRAIN split held out for early stopping, so the "
                        "test set is touched only for final evaluation.")

    # Tracking / registry
    p.add_argument("--mlflow-arn", type=str, default=os.environ.get("MLFLOW_APP_ARN"),
                   help="ARN of your SageMaker MLflow APP (not a Tracking Server).")
    p.add_argument("--mlflow-experiment", type=str, default="northstar-churn")
    p.add_argument("--run-name", type=str, default=None)
    p.add_argument("--register", action="store_true",
                   help="Register the model as PendingManualApproval (use for the graded run).")
    p.add_argument("--model-package-group", type=str, default=MODEL_PACKAGE_GROUP)

    p.add_argument("--model-dir", type=str,
                   default=os.environ.get("SM_MODEL_DIR", "./model"))
    p.add_argument("--output-data-dir", type=str,
                   default=os.environ.get("SM_OUTPUT_DATA_DIR", "./output"))
    return p.parse_args()


# ── Feature Store Loading ──────────────────────────────────────────────────────

def load_features_from_feature_store(feature_group_name: str,
                                     start_date: str,
                                     end_date: str,
                                     artifacts_bucket: str) -> pd.DataFrame:
    """Load features from the Feature Store offline store through Athena."""
    if not SAGEMAKER_AVAILABLE:
        raise RuntimeError("SageMaker SDK not available - use --local-data-path for local testing")

    # event_time is Fractional epoch SECONDS; convert the date bounds.
    start_epoch = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    end_epoch = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()

    session = Session()
    feature_group = FeatureGroup(name=feature_group_name, sagemaker_session=session)
    query = feature_group.athena_query()

    # Always select churn_risk_score so --include-risk-score works; it only
    # enters the model if the flag is set.
    select_cols = FEATURE_COLUMNS + [BASELINE_COLUMN]

    # Dedup (offline store is append-only), drop soft-deleted rows, and ORDER BY
    # customer_id so the row order -- and therefore the split -- is reproducible.
    query_string = f"""
        WITH ranked AS (
            SELECT
                customer_id,
                {", ".join(select_cols)},
                {LABEL_COLUMN},
                {SLICE_COLUMN},
                event_time,
                ROW_NUMBER() OVER (
                    PARTITION BY customer_id
                    ORDER BY event_time DESC, write_time DESC
                ) AS rn
            FROM "{query.table_name}"
            WHERE event_time BETWEEN {start_epoch} AND {end_epoch}
              AND NOT is_deleted
        )
        SELECT
            customer_id,
            {", ".join(select_cols)},
            {LABEL_COLUMN},
            {SLICE_COLUMN}
        FROM ranked
        WHERE rn = 1
        ORDER BY customer_id
    """

    query.run(query_string=query_string,
              output_location=f"s3://{artifacts_bucket}/artifacts/athena-results/")
    query.wait()

    # The evidence script looks this exact line up in Athena.
    execution = query.get_query_execution()["QueryExecution"]
    print(f"Athena QueryExecutionId: {execution['QueryExecutionId']}")
    state = execution["Status"]["State"]
    if state != "SUCCEEDED":
        raise RuntimeError(f"Athena query {state}: "
                           f"{execution['Status'].get('StateChangeReason', 'no reason given')}")

    df = query.as_dataframe()
    print(f"Athena returned {len(df):,} rows")
    if len(df) == 0:
        raise RuntimeError("Athena returned zero rows. Is the Feature Group populated "
                           "(re-run the Lab 2 feature-engineering job)?")
    return df


def load_features_local(path: str) -> pd.DataFrame:
    """DEV ONLY: load features from a local CSV."""
    print(f"Loading features from local file: {path}")
    df = pd.read_csv(path)
    missing = [c for c in FEATURE_COLUMNS + [LABEL_COLUMN] if c not in df.columns]
    if missing:
        raise ValueError(f"Local data missing required columns: {missing}")
    if SLICE_COLUMN not in df.columns:
        print(f"WARNING: '{SLICE_COLUMN}' not in local data — slice evaluation disabled")
    return df


# ── Preprocessing ──────────────────────────────────────────────────────────────

def preprocess_features(df: pd.DataFrame, features: list):
    """Return (X, y). Missing feature values stay NaN: XGBoost learns a default
    split direction for them, which avoids a sentinel (e.g. -1) that would look
    like 'very recent' on days_since_last_purchase."""
    print(f"Preprocessing {len(df):,} samples...")
    missing = [c for c in features if c not in df.columns]
    if missing:
        raise ValueError(f"Data missing feature columns: {missing}")
    X = df[features].astype(float).values
    y = df[LABEL_COLUMN].values.astype(int)
    n_nan = int(np.isnan(X).sum())
    print(f"  Positive class rate: {y.mean():.1%}")
    print(f"  Feature matrix shape: {X.shape}; missing values left as NaN: {n_nan}")
    return X, y


# ── Training ───────────────────────────────────────────────────────────────────

def train_model(X_fit, y_fit, X_es, y_es, args, features) -> xgb.Booster:
    dfit = xgb.DMatrix(X_fit, label=y_fit, feature_names=features)
    des = xgb.DMatrix(X_es, label=y_es, feature_names=features)

    # Class imbalance (~22% positives): scale_pos_weight = negatives/positives,
    # derived from the training rows so the weight matches the data actually fit.
    spw = (args.scale_pos_weight if args.scale_pos_weight is not None
           else float((y_fit == 0).sum() / max((y_fit == 1).sum(), 1)))
    args.resolved_scale_pos_weight = spw

    params = {
        "objective": "binary:logistic",
        # Early stopping uses the LAST metric: keep "auc" last (defect 49).
        "eval_metric": ["logloss", "auc"],
        "max_depth": args.max_depth,
        "eta": args.eta,
        "min_child_weight": args.min_child_weight,
        "subsample": args.subsample,
        "colsample_bytree": args.colsample_bytree,
        "scale_pos_weight": spw,
        "seed": args.seed,
        "verbosity": 1,
    }
    print(f"\nTraining XGBoost with params: {json.dumps(params, indent=2)}")
    model = xgb.train(
        params=params,
        dtrain=dfit,
        num_boost_round=args.num_round,
        evals=[(dfit, "train"), (des, "early_stop")],
        early_stopping_rounds=20,
        verbose_eval=25,
    )
    return model


def train_recency_baseline(X_fit, y_fit, X_test, features, seed) -> np.ndarray:
    """Model over days_since_last_purchase ALONE, same training rows and test
    rows as the full model. (A constant predictor would have AUC 0.5 and prove
    nothing.)"""
    i = features.index(BASELINE_FEATURE)
    dtr = xgb.DMatrix(X_fit[:, [i]], label=y_fit, feature_names=[BASELINE_FEATURE])
    dte = xgb.DMatrix(X_test[:, [i]], feature_names=[BASELINE_FEATURE])
    spw = float((y_fit == 0).sum() / max((y_fit == 1).sum(), 1))
    params = {"objective": "binary:logistic", "eval_metric": "auc",
              "max_depth": 4, "eta": 0.1, "subsample": 0.9,
              "colsample_bytree": 0.9, "scale_pos_weight": spw, "seed": seed}
    return xgb.train(params, dtr, num_boost_round=200).predict(dte)


def bootstrap_lift_ci(y_true, proba, baseline_proba,
                      n=BOOTSTRAP_N, seed=BOOTSTRAP_SEED, alpha=0.05):
    """Paired percentile CI for (model AUC - baseline AUC): each replicate
    resamples rows ONCE and scores both models on those rows."""
    rng = np.random.default_rng(seed)
    y_true = np.asarray(y_true)
    idx = np.arange(len(y_true))
    diffs = []
    for _ in range(n):
        s = rng.choice(idx, size=len(idx), replace=True)
        ys = y_true[s]
        if len(np.unique(ys)) < 2:
            continue
        diffs.append(roc_auc_score(ys, proba[s]) - roc_auc_score(ys, baseline_proba[s]))
    if len(diffs) < n // 2:
        raise ValueError("Too few usable bootstrap replicates for a confidence interval.")
    d = np.sort(diffs)
    return float(np.quantile(d, alpha / 2)), float(np.quantile(d, 1 - alpha / 2))


# ── Evaluation ─────────────────────────────────────────────────────────────────

def predict(model, X, features) -> np.ndarray:
    return model.predict(xgb.DMatrix(X, feature_names=features))


def top_decile_mask(proba: np.ndarray) -> np.ndarray:
    """Customers in the top 10% by score: the retention team's contact budget."""
    return proba >= np.percentile(proba, 90)


def evaluate_model(model, X_test, y_test, baseline_proba, features):
    """Returns (metrics, failures, proba). Does NOT raise on a missed gate, so
    experimental runs still get tracked; main() decides whether to register."""
    proba = predict(model, X_test, features)
    auc_roc = roc_auc_score(y_test, proba)

    mask = top_decile_mask(proba)
    precision_top10 = y_test[mask].mean() if mask.sum() > 0 else 0.0
    recall_top10 = y_test[mask].sum() / y_test.sum() if y_test.sum() > 0 else 0.0

    baseline_auc = roc_auc_score(y_test, baseline_proba)
    lift_lo, lift_hi = bootstrap_lift_ci(y_test, proba, baseline_proba)

    metrics = {
        "auc_roc": round(float(auc_roc), 4),
        "precision_top10": round(float(precision_top10), 4),
        "recall_top10": round(float(recall_top10), 4),
        "auc_vs_baseline": round(float(auc_roc - baseline_auc), 4),
        "baseline_auc": round(float(baseline_auc), 4),
        "lift_ci_low": round(lift_lo, 4),
        "lift_ci_high": round(lift_hi, 4),
        "positive_rate_val": round(float(y_test.mean()), 4),
        "n_val_samples": int(len(y_test)),
        "eval_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    print("\n── Evaluation Results (test set) ───────────────────")
    print(f"  {'auc_roc':25s}: {metrics['auc_roc']:.4f} (reported, not gated)")
    print(f"  {'baseline_auc (recency)':25s}: {metrics['baseline_auc']:.4f}")
    failures = []
    for name, threshold in EVAL_THRESHOLDS.items():
        v = metrics[name]
        ok = v >= threshold
        print(f"  {name:25s}: {v:.4f} (threshold: {threshold:.2f}) {'PASS' if ok else 'FAIL'}")
        if not ok:
            failures.append(f"{name}={v:.4f} < {threshold}")
    ci_ok = lift_lo > 0
    print(f"  {'auc_lift 95% CI':25s}: [{lift_lo:.4f}, {lift_hi:.4f}] "
          f"(must exclude 0) {'PASS' if ci_ok else 'FAIL'}")
    if not ci_ok:
        failures.append(f"lift CI [{lift_lo:.4f}, {lift_hi:.4f}] includes zero")
    print("  All gates passed" if not failures else f"  GATES FAILED: {'; '.join(failures)}")
    return metrics, failures, proba


def evaluate_slices(model, X_val, y_val, slice_column, features=FEATURE_COLUMNS) -> dict:
    """AUC and recall@top-10% per tier, always with n and positives.

    Recall uses the GLOBAL top-10% score cutoff: the contact budget is set
    across all customers, so a tier's recall is the share of its churners the
    program would actually reach. A tier is flagged if its recall is >10pp
    below aggregate, and marked too_small if it has < MIN_SLICE_POSITIVES
    positives (its metrics cannot support a claim)."""
    proba = predict(model, X_val, features)
    in_top = top_decile_mask(proba)
    y_val = np.asarray(y_val)
    slice_column = np.asarray(slice_column)
    aggregate_recall = float(y_val[in_top].sum() / max(y_val.sum(), 1))

    results = {}
    for tier in sorted(np.unique(slice_column)):
        m = slice_column == tier
        yt, pt = y_val[m], proba[m]
        n, pos = int(m.sum()), int(yt.sum())
        auc_t = float(roc_auc_score(yt, pt)) if 0 < pos < n else float("nan")
        recall_t = float(yt[in_top[m]].sum() / pos) if pos > 0 else float("nan")
        results[str(tier)] = {
            "tier": str(tier),
            "n": n,
            "positives": pos,
            "auc": round(auc_t, 4),
            "recall": round(recall_t, 4),
            "too_small": bool(pos < MIN_SLICE_POSITIVES),
            "recall_gap_flag": bool(not np.isnan(recall_t) and recall_t < aggregate_recall - 0.10),
            "aggregate_recall": round(aggregate_recall, 4),
        }
    return results


def print_slices(slice_results: dict):
    print("\n── Slice evaluation by loyalty tier ────────────────")
    print(f"  {'tier':10s} {'n':>6s} {'pos':>5s} {'AUC':>7s} {'recall':>7s}  notes")
    for r in slice_results.values():
        notes = []
        if r["too_small"]:
            notes.append(f"TOO SMALL (<{MIN_SLICE_POSITIVES} positives)")
        if r["recall_gap_flag"]:
            notes.append("recall >10pp below aggregate")
        print(f"  {r['tier']:10s} {r['n']:6d} {r['positives']:5d} {r['auc']:7.4f} "
              f"{r['recall']:7.4f}  {'; '.join(notes)}")


def save_evidence_files(model, y_test, proba, slice_results, features, out_dir):
    """slice-evaluation.csv, confusion-matrix.png, feature-importance.png"""
    os.makedirs(out_dir, exist_ok=True)

    pd.DataFrame(list(slice_results.values())).to_csv(
        os.path.join(out_dir, "slice-evaluation.csv"), index=False)

    # Confusion matrix at the top-10% score cutoff (the operating point)
    pred = top_decile_mask(proba).astype(int)
    cm = confusion_matrix(y_test, pred, labels=[0, 1])
    fig, ax = plt.subplots(figsize=(4.5, 4))
    ax.imshow(cm, cmap="Blues")
    for (i, j), v in np.ndenumerate(cm):
        ax.text(j, i, f"{v:,}", ha="center", va="center",
                color="white" if v > cm.max() / 2 else "black")
    ax.set_xticks([0, 1], ["not contacted", "contacted (top 10%)"], fontsize=8)
    ax.set_yticks([0, 1], ["stayed", "churned"])
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title("Confusion matrix @ top-10% cutoff (test set)", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "confusion-matrix.png"), dpi=150)
    plt.close(fig)

    # Feature importance (gain)
    score = model.get_score(importance_type="gain")
    items = sorted(((f, score.get(f, 0.0)) for f in features), key=lambda t: t[1])
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.barh([f for f, _ in items], [v for _, v in items], color="#3b6ea8")
    ax.set_xlabel("Average gain")
    ax.set_title("XGBoost feature importance (gain)")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "feature-importance.png"), dpi=150)
    plt.close(fig)
    print(f"\n✓ Wrote slice-evaluation.csv, confusion-matrix.png, "
          f"feature-importance.png to {out_dir}")


# ── Experiment Tracking (MLflow App) ───────────────────────────────────────────

def track_run(args, metrics: dict, scale_pos_weight, slice_results=None,
              artifact_dir=None) -> None:
    """Log this run to the SageMaker MLflow APP (free). NEVER a Tracking Server."""
    if not args.mlflow_arn:
        print("\n(no --mlflow-arn given; skipping experiment tracking)")
        return

    import mlflow  # needs `mlflow` AND `sagemaker-mlflow` installed

    mlflow.set_tracking_uri(args.mlflow_arn)
    mlflow.set_experiment(args.mlflow_experiment)

    with mlflow.start_run(run_name=args.run_name):
        mlflow.log_params({
            "max_depth": args.max_depth,
            "eta": args.eta,
            "num_round": args.num_round,
            "min_child_weight": args.min_child_weight,
            "subsample": args.subsample,
            "colsample_bytree": args.colsample_bytree,
            "scale_pos_weight": round(float(scale_pos_weight), 4),
            "include_risk_score": args.include_risk_score,
            "seed": args.seed,
            "early_stopping_fraction": args.early_stopping_fraction,
            "xgboost_version": xgb.__version__,
        })
        mlflow.log_metrics({k: v for k, v in metrics.items()
                            if isinstance(v, (int, float)) and not isinstance(v, bool)})
        for r in (slice_results or {}).values():
            for key in ("auc", "recall"):
                if not np.isnan(r[key]):
                    mlflow.log_metric(f"slice_{r['tier']}_{key}", r[key])
            mlflow.log_metric(f"slice_{r['tier']}_n", r["n"])
        if artifact_dir:
            try:
                for fname in ("slice-evaluation.csv", "confusion-matrix.png",
                              "feature-importance.png"):
                    path = os.path.join(artifact_dir, fname)
                    if os.path.exists(path):
                        mlflow.log_artifact(path)
            except Exception as e:  # artifacts are nice-to-have; metrics are graded
                print(f"WARNING: could not log MLflow artifacts: {e}")
    print(f"\n✓ Logged run '{args.run_name}' to MLflow App")


# ── Model Saving & Registry ────────────────────────────────────────────────────

def save_model(model, metrics, args, features) -> str:
    os.makedirs(args.model_dir, exist_ok=True)
    model_path = os.path.join(args.model_dir, "model.xgb")
    model.save_model(model_path)
    print(f"\n✓ Model saved to {model_path}")

    metadata = {
        "feature_columns": features,
        "label_column": LABEL_COLUMN,
        "hyperparameters": {"max_depth": args.max_depth, "eta": args.eta,
                            "num_round": args.num_round},
        "xgboost_version": xgb.__version__,
        "evaluation_metrics": metrics,
        "training_date": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(args.model_dir, "model_metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)
    return model_path


def register_model(model_path: str, metrics: dict, args) -> str:
    """Upload the model under artifacts/ and register it as PendingManualApproval.
    Never auto-approves."""
    if not SAGEMAKER_AVAILABLE:
        raise RuntimeError("sagemaker<3 required to look up the XGBoost image URI")
    from sagemaker import image_uris

    region = boto3.session.Session().region_name or "us-east-1"
    sm = boto3.client("sagemaker", region_name=region)
    s3 = boto3.client("s3", region_name=region)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tar_path = os.path.join(args.model_dir, "model.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model_path, arcname=os.path.basename(model_path))
    key = f"artifacts/models/churn/{stamp}/model.tar.gz"
    s3.upload_file(tar_path, args.artifacts_bucket, key)
    model_data_url = f"s3://{args.artifacts_bucket}/{key}"

    try:
        sm.describe_model_package_group(ModelPackageGroupName=args.model_package_group)
    except ClientError:
        sm.create_model_package_group(
            ModelPackageGroupName=args.model_package_group,
            ModelPackageGroupDescription="NorthStar churn models (Lab 3+)")

    image = image_uris.retrieve("xgboost", region, version="1.7-1")
    metadata = {k: str(v) for k, v in metrics.items()}
    metadata["xgboost_version_trained"] = xgb.__version__
    if args.run_name:
        metadata["run_name"] = args.run_name

    resp = sm.create_model_package(
        ModelPackageGroupName=args.model_package_group,
        ModelPackageDescription=(f"Churn model {args.run_name or stamp}: "
                                 f"AUC {metrics['auc_roc']}, "
                                 f"P@10% {metrics['precision_top10']}, "
                                 f"R@10% {metrics['recall_top10']}"),
        InferenceSpecification={
            "Containers": [{"Image": image, "ModelDataUrl": model_data_url}],
            "SupportedContentTypes": ["text/csv"],
            "SupportedResponseMIMETypes": ["text/csv"],
        },
        ModelApprovalStatus="PendingManualApproval",
        CustomerMetadataProperties=metadata,
    )
    arn = resp["ModelPackageArn"]
    print(f"✓ Registered {arn} (PendingManualApproval)")
    return arn


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    os.makedirs(args.model_dir, exist_ok=True)
    os.makedirs(args.output_data_dir, exist_ok=True)

    print("=" * 60)
    print("NorthStar Churn Prediction — Training Script")
    print(f"XGBoost {xgb.__version__} | include_risk_score={args.include_risk_score}")
    print("=" * 60)

    # 1. Load features
    if args.local_data_path:
        print("WARNING: --local-data-path set: this is NOT a graded (Athena) run.")
        df = load_features_local(args.local_data_path)
    else:
        df = load_features_from_feature_store(
            args.feature_group_name, args.training_start_date,
            args.training_end_date, args.artifacts_bucket)

    # 1b. Drop unlabeled rows BEFORE extracting X, y, tiers so all share row order.
    df = df.dropna(subset=[LABEL_COLUMN]).reset_index(drop=True)

    # 2. Preprocess
    features = get_features(args)
    X, y = preprocess_features(df, features)
    if SLICE_COLUMN in df.columns:
        tiers = df[SLICE_COLUMN].to_numpy(dtype=str)  # plain str array (pandas 3 safe)
    else:
        tiers = np.array(["unknown"] * len(df))

    # 3. Train/test split (70/30, stratified). The 30% is the TEST set and is
    #    used only for final evaluation. Early stopping uses a slice of TRAIN.
    X_train, X_test, y_train, y_test, tier_train, tier_test = train_test_split(
        X, y, tiers, test_size=0.30, random_state=args.seed, stratify=y)
    if args.early_stopping_fraction > 0:
        X_fit, X_es, y_fit, y_es = train_test_split(
            X_train, y_train, test_size=args.early_stopping_fraction,
            random_state=args.seed, stratify=y_train)
    else:
        print("WARNING: early stopping on the TEST set (optimistic metrics)")
        X_fit, y_fit, X_es, y_es = X_train, y_train, X_test, y_test
    print(f"\nFit: {len(X_fit):,} | Early-stop: {len(X_es):,} | Test: {len(X_test):,}")

    # 4. Train
    model = train_model(X_fit, y_fit, X_es, y_es, args, features)
    print(f"Best iteration: {getattr(model, 'best_iteration', 'n/a')}")

    # 5. Evaluate (aggregate, baseline + CI, slices)
    baseline_proba = train_recency_baseline(X_fit, y_fit, X_test, features, args.seed)
    metrics, failures, proba = evaluate_model(model, X_test, y_test, baseline_proba, features)
    metrics["n_train_samples"] = int(len(X_fit))
    slice_results = evaluate_slices(model, X_test, y_test, tier_test, features)
    print_slices(slice_results)
    save_evidence_files(model, y_test, proba, slice_results, features, args.output_data_dir)

    # 6. Write metrics BEFORE tracking/registering so all three agree.
    metrics_path = os.path.join(args.output_data_dir, "evaluation_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)

    # 7. Track in MLflow App (every run, pass or fail: failed experiments are data)
    track_run(args, metrics, getattr(args, "resolved_scale_pos_weight", None),
              slice_results, args.output_data_dir)

    # 8. Save + register (only the graded run, and only if the gates passed)
    model_path = save_model(model, metrics, args, features)
    if args.register:
        if failures:
            print(f"\n✗ NOT registering: gates failed ({'; '.join(failures)})")
        else:
            register_model(model_path, metrics, args)
    else:
        print("\n(--register not set; skipping Model Registry)")

    print("\n" + "=" * 60)
    print(f"Training complete. AUC-ROC: {metrics['auc_roc']:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
