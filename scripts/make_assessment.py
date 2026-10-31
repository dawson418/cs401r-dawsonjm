"""python scripts/make_assessment.py  -> writes docs/lab4-xops-assessment.md using real numbers
from docs/lab4-build-green.log and docs/lab4-failure-demo.txt (run after both exist)."""
import re, sys
g = open("docs/lab4-build-green.log", errors="ignore").read()
m = re.search(r"champion v(\d+) auc=([\d.]+); candidate auc=([\d.]+)", g)
if not m:
    sys.exit("no 'champion v.. auc=..' line in docs/lab4-build-green.log - is that the final green build?")
cv, cauc, nauc = m.groups()
fr = re.search(r"(\d+) failed", g)
n_pass = len(re.findall(r" PASSED", g))

md = f"""# Lab 4: XOps Assessment

## Pipeline Stage Mapping

| Five-phase lifecycle stage | Where it lives |
|---|---|
| 1. Source | CodePipeline `Source` stage in `pipeline.yaml` (GitHub connection, branch `main`); every push starts a run |
| 2. Test | CodeBuild `pre_build` in `buildspec.yml` runs `tests/test_data.py` and `tests/test_features.py`; a failure stops the build before any training (`docs/lab4-failure-demo.txt`) |
| 3. Train | CodeBuild `build` phase starts the SageMaker Pipeline `northstar-churn-pipeline` (spot `TrainChurnModel` step running `models/churn/churn_model.py` through `models/churn/train_sagemaker.py`), then `tests/test_model.py` and `tests/test_fairness.py` gate its metrics |
| 4. Register | `RegisterChurnModel` adds a `PendingManualApproval` package to `northstar-churn-models`; the lineage is stored with `scripts/write_lineage.py` |
| 5. Approve/Deploy | CodePipeline `ManualApproval` stage publishing to the `northstar-model-approvals` SNS topic; deployment itself arrives in Lab 5 |

## Champion-Challenger

The champion is the newest `Approved` package in `northstar-churn-models`. A candidate is promoted only if ALL hold: `auc_roc >= champion_auc - 0.02` (enforced by `test_candidate_not_worse_than_champion` in `tests/test_model.py`), `precision_top10 >= 0.50`, `recall_top10 >= 0.25`, and the 95% bootstrap CI on AUC lift over the recency-only baseline excludes zero (`lift_ci_low > 0`). Anything else is binary: fail, not registered. In the final green build the test compared champion v{cv} (AUC {cauc}) with the candidate (AUC {nauc}) and passed (`docs/lab4-build-green.log`).

## Retraining Triggers

1. **Scheduled:** an Amazon EventBridge schedule rule, `cron(0 6 ? * MON *)` (every Monday 06:00 UTC), whose target starts the `northstar-pipeline` CodePipeline execution, so the weekly run re-tests the data, retrains, and registers a new `PendingManualApproval` package.
2. **Performance-based:** a CloudWatch alarm on a custom metric `NorthStar/Churn rolling_auc_7d` (published by a SageMaker Model Monitor model-quality job once labels arrive) with threshold `< 0.70` for 1 of 1 day; its state change fires an EventBridge rule that starts the same CodePipeline. Neither trigger needs a human decision; the human gate stays at ManualApproval.

## DataOps Maturity

Current level: 2 (repeatable and tested, not yet monitored).
Evidence: the Glue ETL in `glue-scripts/feature_engineer.py` is reproducible Terraform-built infrastructure; `data/feature_engineering.py` extracts its logic into pandas functions covered by `tests/test_features.py`; `tests/test_data.py` checks schema, grain, leakage, bounds and 48-hour freshness on every build and fails when data is missing. {n_pass} test lines passed in the final build (`docs/lab4-build-green.log`).
Gap to Level 3: no automated scheduling or data-quality monitoring of the feature job. It is started by hand (`aws glue start-job-run`), so freshness is only caught after it goes stale, as the failing 48-hour test would show.
Top priority investment: an EventBridge schedule that runs `northstar-dev-feature-engineer` nightly plus AWS Glue Data Quality rules on the features table.

## MLOps Maturity

Current level: 3 (automated CI/CD with gated promotion).
Evidence: `buildspec.yml` and `pipeline.yaml` run tests, train and register on every push; the deliberate failure stopped the run in PRE_BUILD with no new registry version and an SNS alarm email (`docs/lab4-failure-demo.txt`, `docs/lab4-build-failed.log`); packages carry commit SHA, data URI and metrics (`docs/lab4-model-package.json`); experiments are tracked in an MLflow App (`docs/lab4-mlflow-runs.txt`).
Gap to Level 4: no production monitoring, so nothing detects drift or fires the performance trigger above; the fairness gap check only flags and does not block (`tests/test_fairness.py`).
Top priority investment: SageMaker Model Monitor with data-quality and model-quality baselines on the Lab 6 endpoint, wired to the CloudWatch alarm that starts retraining.
"""
open("docs/lab4-xops-assessment.md", "w").write(md)
print("written;", len(md.split()), "words total")
