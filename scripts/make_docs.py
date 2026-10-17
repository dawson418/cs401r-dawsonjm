import json, os
import pandas as pd, xgboost as xgb
EV = "docs/lab3-evidence"
m = json.load(open(f"{EV}/evaluation_metrics.json"))
sl = pd.read_csv(f"{EV}/slice-evaluation.csv")
meta = json.load(open("model/model_metadata.json"))
feats, xv = meta["feature_columns"], meta["xgboost_version"]
b = xgb.Booster(); b.load_model("model/model.xgb")
g = b.get_score(importance_type="gain"); tot = sum(g.values())
rank = sorted(((f, g.get(f, 0) / tot) for f in feats), key=lambda t: -t[1])
top3, bot3 = rank[:3], rank[-3:]
def tbl(df):
    return "\n".join(["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)] +
                     ["| " + " | ".join(map(str, r)) + " |" for r in df.values])
runs = ""
try:
    import mlflow
    mlflow.set_tracking_uri(os.environ["MLFLOW_APP_ARN"])
    r = mlflow.search_runs(experiment_names=["northstar-churn"])
    r = r[["tags.mlflow.runName", "params.max_depth", "params.eta", "params.num_round",
           "params.include_risk_score", "metrics.auc_roc", "metrics.precision_top10", "metrics.recall_top10"]]
    r.columns = ["run", "max_depth", "eta", "num_round", "risk_score", "auc", "p@10%", "r@10%"]
    runs = tbl(r.round(4))
except Exception as e:
    runs = f"(could not read MLflow runs: {e})"
ok = sl[~sl.too_small]
weak = ok.sort_values("auc").iloc[0] if len(ok) else None
small = ", ".join(sl[sl.too_small].tier) or "none"
gap = ", ".join(sl[sl.recall_gap_flag].tier) or "none"
weak_txt = (f"The weakest tier with enough data is **{weak.tier}** (AUC {weak.auc}, recall {weak.recall}, n={weak.n}, "
            f"{weak.positives} churners)." if weak is not None else "Every tier is too small to conclude from.")
rep = f"""# Lab 3 Evaluation Report (Track A: churn)

XGBoost {xv}, seed 42, stratified 70/30 split (test n={m['n_val_samples']}); 15% of the training split was held out for early stopping so the test set was used only for final evaluation. Data came from the Feature Store offline store via Athena.

| Metric | Value | Threshold |
|---|---|---|
| AUC-ROC (test) | {m['auc_roc']} | report only |
| Precision @ top 10% | {m['precision_top10']} | >= 0.50 |
| Recall @ top 10% | {m['recall_top10']} | >= 0.25 |
| Recency-only baseline AUC | {m['baseline_auc']} | n/a |
| AUC lift over baseline | {m['auc_vs_baseline']} | CI must exclude 0 |
| Lift 95% CI (paired bootstrap, 2,000 resamples) | [{m['lift_ci_low']}, {m['lift_ci_high']}] | excludes 0 |

Scale_pos_weight was derived as negatives/positives from the training rows (about 22% churners), not hardcoded. The 1.7 SageMaker container would give slightly different numbers than XGBoost {xv}.

## Experiments
{runs}

The run with risk_score=True includes churn_risk_score, a recency heuristic; the graded run excludes it so the baseline comparison is not circular.

## Confusion matrix (top-10% cutoff) and feature importance
![confusion matrix](lab3-evidence/confusion-matrix.png)
![feature importance](lab3-evidence/feature-importance.png)

Top features by gain: {', '.join(f'{f} ({s:.0%})' for f, s in top3)}. Lowest: {', '.join(f'{f} ({s:.0%})' for f, s in bot3)}.

## Slice evaluation by loyalty tier (`lab3-evidence/slice-evaluation.csv`)
{tbl(sl)}

{weak_txt} Tiers too small to conclude from (fewer than 30 test positives): {small}. Tiers with recall more than 10pp below aggregate: {gap}. Recall uses the global top-10% cutoff, i.e. the share of each tier's churners the contact budget would reach.
"""
open("docs/lab3-evaluation-report.md", "w").write(rep)
d = f"""# Lab 3 Model Design

**Track B (offer generation, RAG)**

## Churn model
NorthStar has about 10,000 customers and a handful of tabular features, with 22% churners. At that size a gradient-boosted tree model is the right tool: it captures interactions (for example, low category diversity combined with recent purchases) that logistic regression cannot without hand-built terms, and a neural network would have far more capacity than 7,000 training rows can support. Tree models also give gain importances and per-tier slices the retention team can read. I would switch if the input became raw event sequences (clickstream) at much larger scale, or if the business needed calibrated per-customer explanations at which point I would add SHAP on top of the same model.

## What the features bought
Recency-only baseline AUC was {m['baseline_auc']}; the full model reached {m['auc_roc']}, a lift of {m['auc_vs_baseline']} with a 95% paired-bootstrap CI of [{m['lift_ci_low']}, {m['lift_ci_high']}]. The interval excludes zero, so the engineered features did measurable work, but the lift is modest, not transformative. The model leans most on {', '.join(f'{f} ({s:.0%})' for f, s in top3)}. The weakest features by gain were {', '.join(f'{f} ({s:.0%})' for f, s in bot3)}, and I treat those as close to decorative here. {weak_txt} Tiers too small to conclude from: {small}. I excluded churn_risk_score from the graded model because it is a recency heuristic and would make the baseline comparison circular; I also ran it as a separate experiment to check.

## LLM system
I chose RAG over fine-tuning because NorthStar's policies (the 30-day return window, tier benefits) change, and a fine-tuned model would bake in a stale snapshot and could not cite which clause supports a claim. With RAG, an offer is traceable to retrieved chunk IDs and updating a policy means re-indexing a document, not retraining. The primary production risk is a faithfulness failure: promising a benefit the customer's tier does not carry. The feature store's loyalty tier is derived from lifetime value while policy defines tier by trailing 12-month spend, so near a threshold the two disagree. My system prompt only allows tier benefits that appear in retrieved policy text, and falls back to generic wording otherwise. In production the tier should be read from the system of record at generation time.

## What I would do differently with 10x time or data
I would replace the LLM-judged scores with a deterministic claim checker that extracts every number, deadline and benefit from an offer and verifies each against the policy corpus, run on hundreds of generated offers instead of four test cases. For the churn model I would validate on a true temporal split across several cutoff dates instead of a single random split, and move from predicting churn to modeling uplift so the retention budget goes to customers an offer can actually change.
"""
open("docs/lab3-model-design.md", "w").write(d)
print("wrote docs/lab3-evaluation-report.md and docs/lab3-model-design.md")
