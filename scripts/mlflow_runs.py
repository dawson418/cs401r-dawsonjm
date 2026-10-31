"""Lab 4 Task 3: log >=4 hyperparameter combos to your MLflow App and save docs/lab4-mlflow-runs.txt.

usage (laptop, AWS creds active):
  python scripts/mlflow_runs.py --tracking-uri <mlflow-app ARN> --channel /tmp/channel
Uses the same train() as the pipeline, so the metrics are the model you ship."""
import argparse, os, sys
import mlflow, pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models", "churn"))
import churn_model as cm  # noqa: E402
from train_sagemaker import read_channel  # noqa: E402

COMBOS = [
    {"max_depth": 3, "eta": 0.10, "num_rounds": 200},
    {"max_depth": 4, "eta": 0.08, "num_rounds": 300},
    {"max_depth": 5, "eta": 0.05, "num_rounds": 400},
    {"max_depth": 6, "eta": 0.03, "num_rounds": 500},
]
EXP = "northstar-churn-lab4"

ap = argparse.ArgumentParser()
ap.add_argument("--tracking-uri", required=True)
ap.add_argument("--channel", default="/tmp/channel")
ap.add_argument("--out", default="docs/lab4-mlflow-runs.txt")
a = ap.parse_args()

df = read_channel(a.channel)
mlflow.set_tracking_uri(a.tracking_uri)
mlflow.set_experiment(EXP)
orig_params, orig_rounds, orig_gate = dict(cm.PARAMS), cm.NUM_ROUNDS, (cm.MIN_PRECISION_TOP10, cm.MIN_RECALL_TOP10)
for i, c in enumerate(COMBOS, 1):
    cm.PARAMS.update(max_depth=c["max_depth"], eta=c["eta"])
    cm.NUM_ROUNDS = c["num_rounds"]
    with mlflow.start_run(run_name=f"lab4-combo-{i}"):
        mlflow.log_params(c)
        try:
            _, m = cm.train(df, seed=42)
            gate = "pass"
        except RuntimeError as e:  # a combo that misses a gate is still a valid experiment
            gate = "gate_fail"
            cm.MIN_PRECISION_TOP10, cm.MIN_RECALL_TOP10 = 0.0, 0.0
            _, m = cm.train(df, seed=42)
            cm.MIN_PRECISION_TOP10, cm.MIN_RECALL_TOP10 = orig_gate
        mlflow.set_tag("gate", gate)
        mlflow.log_metrics({k: float(v) for k, v in m.items()
                            if k in ("auc_roc", "baseline_auc_roc", "auc_lift_over_baseline",
                                     "precision_top10", "recall_top10", "lift_ci_low", "lift_ci_high")})
        print("run", i, c, "auc=%.4f" % m["auc_roc"], gate)
cm.PARAMS.clear(); cm.PARAMS.update(orig_params); cm.NUM_ROUNDS = orig_rounds

runs = mlflow.search_runs(experiment_names=[EXP])
cols = ["run_id", "tags.mlflow.runName", "start_time"] + \
       [c for c in runs.columns if c.startswith(("params.", "metrics."))]
os.makedirs(os.path.dirname(a.out), exist_ok=True)
with open(a.out, "w") as f:
    f.write(f"tracking_uri: {mlflow.get_tracking_uri()}\n\n{runs[cols].to_string()}\n")
print("wrote", a.out)
