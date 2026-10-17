import os, mlflow
mlflow.set_tracking_uri(os.environ["MLFLOW_APP_ARN"])
df = mlflow.search_runs(experiment_names=["northstar-churn"])
df = df[(df["params.include_risk_score"] == "False") & (df["metrics.precision_top10"] >= 0.5)
        & (df["metrics.recall_top10"] >= 0.25) & (df["metrics.lift_ci_low"] > 0)]
print(df[["tags.mlflow.runName", "metrics.auc_roc"]].sort_values("metrics.auc_roc", ascending=False).to_string())
b = df.sort_values("metrics.auc_roc", ascending=False).iloc[0]
print("\nFINAL COMMAND:\npython models/churn/train.py --feature-group-name $FG --artifacts-bucket $BUCKET "
      f"--mlflow-arn $MLFLOW_APP_ARN --max-depth {b['params.max_depth']} --eta {b['params.eta']} "
      f"--num-round {b['params.num_round']} --min-child-weight {b['params.min_child_weight']} "
      f"--subsample {b['params.subsample']} --colsample-bytree {b['params.colsample_bytree']} "
      "--run-name final-graded --register --output-data-dir docs/lab3-evidence "
      "2>&1 | tee docs/lab3-evidence/train-final.log")
