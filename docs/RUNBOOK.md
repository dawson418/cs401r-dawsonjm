# Lab 4 Runbook (CS 401R: XOps + CI/CD + Testing)

Run everything from the repo root. Each step has a **Validate** block: do not continue until it matches.
Steps marked **[HUMAN]** cannot be automated; the person must do them in the console, email or screenshot tool.

Rules: never edit `models/churn/train_sagemaker.py`, `models/churn/pipeline_definition.py`, `buildspec.yml`, `pipeline.yaml`.
Never commit `.env`, `*.tfvars`, keys. If a CodeBuild run fails, read the log tail once; do not blindly retry
(each run costs time). If a step fails twice, stop and report the exact error.

Shell setup used by many steps:
```bash
export AWS_PAGER=""
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
DB=northstar-dev-data-$ACCOUNT
AB=northstar-dev-cicd-artifacts-$ACCOUNT
```

## Part A: Setup

### 1. Merge starter kit + pre-tested files (additive)
```bash
git pull origin main
rm -rf /tmp/tpl /tmp/l4
git clone --depth 1 https://github.com/byu-cs401r4-f26/cs401r-lab4-template /tmp/tpl
rsync -a --ignore-existing --exclude .git /tmp/tpl/ ./
unzip -oq ~/Downloads/lab4_files.zip -d /tmp/l4 && cp -R /tmp/l4/lab4/. ./
printf '\n# Lab 4 local data copies\ndata/processed/\ndata/features/\ndata/northstar-raw-sample.csv\n' >> .gitignore
```
Validate:
```bash
ls buildspec.yml pipeline.yaml pytest.ini requirements.txt tests/conftest.py tests/test_fairness.py \
   models/churn/pipeline_definition.py models/churn/train_sagemaker.py data/feature_engineering.py scripts/lab4_helpers.sh
git check-ignore -v data/feature_engineering.py models/churn/churn_model.py || echo "not ignored - good"
```
All files listed; last line "not ignored - good". (If data/feature_engineering.py is ignored, `git add -f` it later.)

### 2. Python environment
```bash
source .venv/bin/activate
python3 -m pip install -q pytest pandas pyarrow scikit-learn xgboost boto3
```

### 3. Patch IAM (iam:PassRole + training-job support)
```bash
python3 scripts/patch_iam.py infrastructure/modules/iam/main.tf
git diff infrastructure/modules/iam/main.tf | head -30
```
Validate: prints `inserted 2 statement(s)` (re-run prints `already patched`). If it says "send the file", upload that
file to Claude; do not hand-edit repeatedly.

### 4. Rebuild Lab 2 (about 10 min). Wait for it to finish before any Glue job.
```bash
terraform -chdir=infrastructure/environments/dev init -input=false
terraform -chdir=infrastructure/environments/dev apply -auto-approve
ROLE=$(terraform -chdir=infrastructure/environments/dev output -raw ml_engineer_role_arn); echo $ROLE
```
Validate (should print `allowed`; if AccessDenied, skip):
```bash
aws iam simulate-principal-policy --policy-source-arn $ROLE --action-names iam:PassRole --resource-arns $ROLE \
  --context-entries ContextKeyName=iam:PassedToService,ContextKeyValues=sagemaker.amazonaws.com,ContextKeyType=string \
  --query 'EvaluationResults[0].EvalDecision' --output text
```

### 5. Re-run the Lab 2 data pipeline (about 8 min)
```bash
SAMPLE=$(find . -name northstar-raw-sample.csv -not -path './.git/*' | head -1); echo "sample: $SAMPLE"
aws s3 cp "$SAMPLE" s3://$DB/raw/customers/northstar-raw-sample.csv
aws glue start-crawler --name northstar-dev-raw-crawler
until [ "$(aws glue get-crawler --name northstar-dev-raw-crawler --query Crawler.State --output text)" = READY ]; do echo crawling; sleep 10; done
aws glue get-table --database-name northstar_dev --name customers --query 'Table.Name' --output text   # expect: customers
run_glue () { J=$1; R=$(aws glue start-job-run --job-name $J --query JobRunId --output text)
  while :; do S=$(aws glue get-job-run --job-name $J --run-id $R --query JobRun.JobRunState --output text); echo "$(date +%T) $J $S"
    case $S in SUCCEEDED) return 0;; FAILED|ERROR|TIMEOUT|STOPPED) aws glue get-job-run --job-name $J --run-id $R --query JobRun.ErrorMessage --output text; return 1;; esac; sleep 15; done; }
run_glue northstar-dev-transform && run_glue northstar-dev-feature-engineer
```
Validate: both jobs end `SUCCEEDED`; both listings below show parquet files.
```bash
aws s3 ls s3://$DB/processed/customers/ --recursive | head -3
aws s3 ls s3://$DB/features/customers/ --recursive | head -3
```
If a job fails with `Could not find S3 endpoint or NAT gateway`, wait 3 minutes and re-run only that job.

### 6. Run data + feature tests locally against real data
```bash
mkdir -p data/processed data/features
aws s3 cp s3://$DB/raw/customers/northstar-raw-sample.csv data/northstar-raw-sample.csv
aws s3 cp s3://$DB/processed/customers/ data/processed/ --recursive --exclude "*_glue_temp*"
aws s3 cp s3://$DB/features/customers/ data/features/ --recursive
python3 -m pytest tests/test_data.py tests/test_features.py -q 2>&1 | tail -15
```
Validate: `0 failed`. If `test_no_feature_uses_post_cutoff_data` fails, my pandas port in `data/feature_engineering.py`
differs from `glue-scripts/feature_engineer.py`: show the failing assertion and the Glue file to Claude (chat) and
get an exact port. Do not iterate on it blindly.

### 7. Train locally and run model gates
```bash
rm -rf /tmp/channel /tmp/model /tmp/out; mkdir -p /tmp/channel
aws s3 cp s3://$DB/features/customers/ /tmp/channel/ --recursive
python3 models/churn/train_sagemaker.py --train-channel /tmp/channel --model-dir /tmp/model --output-data-dir /tmp/out 2>&1 | tail -4
cp /tmp/out/model_metadata.json /tmp/model/
python3 -m pytest tests/test_model.py tests/test_fairness.py -q -rw -k "not test_candidate_not_worse" \
  --eval-metrics-path /tmp/out/evaluation_metrics.json --model-path /tmp/model/xgboost-model 2>&1 | tail -6
```
Validate: `Servable artifact: /tmp/model/xgboost-model (UBJ)` and `0 failed`. If `Model failed quality gate`, report that line.

## Part B: AWS prerequisites

### 8. Versioned artifacts bucket
```bash
aws s3api create-bucket --bucket "$AB"
aws s3api put-bucket-versioning --bucket "$AB" --versioning-configuration Status=Enabled
aws s3api get-bucket-versioning --bucket "$AB" --query Status --output text      # expect: Enabled
```

### 9. GitHub connection **[HUMAN console step]**
```bash
aws codeconnections create-connection --provider-type GitHub --connection-name northstar-github --query ConnectionArn --output text
```
Console: Developer Tools -> Settings -> Connections -> `northstar-github` -> Update pending connection ->
Install a new app -> choose the GitHub account -> only select the `cs401r-<netid>` repo -> Install -> Connect.
Validate (must print `AVAILABLE`):
```bash
CONN=$(aws codeconnections list-connections --query "Connections[?ConnectionName=='northstar-github'].ConnectionArn | [0]" --output text)
aws codeconnections list-connections --query "Connections[?ConnectionName=='northstar-github'].ConnectionStatus" --output text
```

### 10. Push work FIRST, then deploy the stack (stack creation starts a run on main)
```bash
git add -A && git status --short       # check: no data/processed, no .env, no .zip
git commit -m "Lab 4: tests, churn_model, feature engineering, CI/CD kit"
git push origin main
GH_OWNER=$(git remote get-url origin | sed -E 's#.*github.com[:/]([^/]+)/([^/.]+)(\.git)?$#\1#')
GH_REPO=$(git remote get-url origin | sed -E 's#.*github.com[:/]([^/]+)/([^/.]+)(\.git)?$#\2#'); echo "$GH_OWNER/$GH_REPO"
aws cloudformation deploy --template-file pipeline.yaml --stack-name northstar-cicd \
  --parameter-overrides ProjectName=northstar Environment=dev GitHubOwner=$GH_OWNER GitHubRepo=$GH_REPO \
  GitHubBranch=main ArtifactsBucket="$AB" GitHubConnectionArn="$CONN" SageMakerRoleArn="$ROLE" \
  --capabilities CAPABILITY_NAMED_IAM
source scripts/lab4_helpers.sh
aws sns subscribe --topic-arn "$TOPIC" --protocol email --notification-endpoint dawson.m.1020@gmail.com
```
**[HUMAN]** click "Confirm subscription" in the email. Validate (an ARN, not `PendingConfirmation`):
```bash
aws sns list-subscriptions-by-topic --topic-arn "$TOPIC" --query 'Subscriptions[].SubscriptionArn' --output text
```

## Part C: First green run and champion

### 11. Wait for run 1 (about 8 min)
```bash
source scripts/lab4_helpers.sh
until [ "$(newest_build)" != "None" ]; do sleep 10; done; wait_build None
```
Last line must be `SUCCEEDED`. Validate:
```bash
save_log "$(newest_build)" /tmp/b1.log; grep -E '^=+ .*(passed|failed|error)' /tmp/b1.log
aws sagemaker list-model-packages --model-package-group-name northstar-churn-models \
  --query 'ModelPackageSummaryList[].[ModelPackageVersion,ModelApprovalStatus]' --output text
```
Expect `1  PendingManualApproval`. The regression test shows SKIPPED in this run (nothing Approved yet): expected.
If FAILED: `tail -60 /tmp/b1.log`; if it mentions `ExecuteUserScriptError` also run
`aws logs tail /aws/sagemaker/TrainingJobs --since 30m --format short | tail -40`, then report both. Do not retry blindly.

### 12. Approve version 1 (the champion)
```bash
ARN=$(aws sagemaker list-model-packages --model-package-group-name northstar-churn-models --sort-by CreationTime --sort-order Descending --max-results 1 --query 'ModelPackageSummaryList[0].ModelPackageArn' --output text)
aws sagemaker update-model-package --model-package-arn "$ARN" --model-approval-status Approved
aws sagemaker list-model-packages --model-package-group-name northstar-churn-models \
  --query 'ModelPackageSummaryList[].[ModelPackageVersion,ModelApprovalStatus]' --output text   # expect: 1  Approved
```

## Part D: Failure demo (about 25 min)

### 13. Run in this exact order
```bash
until [ "$(aws cloudwatch describe-alarms --alarm-names northstar-ci-build-failure --query 'MetricAlarms[0].StateValue' --output text)" = OK ]; do echo waiting for OK; sleep 20; done
snap "BEFORE"
OLD=$(newest_build); bash scripts/fail_demo.sh push; wait_build $OLD            # ends FAILED
until [ "$(aws cloudwatch describe-alarms --alarm-names northstar-ci-build-failure --query 'MetricAlarms[0].StateValue' --output text)" = ALARM ]; do date; sleep 20; done
sleep 60
snap "AFTER FAILED RUN"
save_log "$(newest_build)" docs/lab4-build-failed.log
grep -c "DELIBERATE FAILURE" docs/lab4-build-failed.log                          # expect 1 or more
```
Validate the AFTER FAILED RUN snapshot in `docs/lab4-failure-demo.txt`: it shows `PRE_BUILD FAILED` and no `BUILD` line;
newest package is still version 1; the alarm history contains `Successfully executed action`.

**[HUMAN]** Open the Gmail message with subject `ALARM: "northstar-ci-build-failure"` (received time visible in the header)
and take a screenshot (Shift-Cmd-4). Then:
```bash
mv "$(ls -t ~/Desktop/Screenshot* | head -1)" docs/lab4-alarm-email.png
```
Revert (this run is the FINAL green run):
```bash
OLD=$(newest_build); bash scripts/fail_demo.sh revert; wait_build $OLD           # ends SUCCEEDED
until [ "$(aws cloudwatch describe-alarms --alarm-names northstar-ci-build-failure --query 'MetricAlarms[0].StateValue' --output text)" = OK ]; do sleep 20; done
snap "AFTER REVERT"
FINAL=$(newest_build); save_log "$FINAL" docs/lab4-build-green.log
grep -E "champion v[0-9]+ auc|test_candidate_not_worse|FAIRNESS" docs/lab4-build-green.log
```
Validate: `champion v1 auc=...; candidate auc=...` and `test_candidate_not_worse_than_champion PASSED` (not SKIPPED).

## Part E: Remaining evidence

### 14. Lineage + MLflow runs
```bash
python3 scripts/write_lineage.py            # prints metadata, saves docs/lab4-model-package.json
git cat-file -t "$(python3 -c "import json;print(json.load(open('docs/lab4-model-package.json'))['CustomerMetadataProperties']['commit_sha'])")"   # expect: commit
python3 -m pip install -q mlflow sagemaker-mlflow
aws sagemaker list-mlflow-apps --query 'Summaries[].[Name,Status,Arn]' --output text
```
Take the ARN containing `:mlflow-app/` and run:
```bash
python3 scripts/mlflow_runs.py --tracking-uri "<ARN>" --channel /tmp/channel
grep -c "lab4-combo" docs/lab4-mlflow-runs.txt        # expect 4
```
If the app list is empty (app deleted after Lab 3), stop and ask Claude (chat) with the Lab 3 MLflow setup file.

### 15. Assessment, capture, audit
```bash
python3 scripts/make_assessment.py
capture_all "$FINAL"
python3 scripts/audit_evidence.py
```
Validate: audit ends `ALL GOOD`. Also open `docs/lab4-build-green.log` and `docs/lab4-pipeline-runs.txt` (not empty;
pipeline-runs shows builds SUCCEEDED, FAILED, SUCCEEDED). If a cited path FAILs (e.g. glue-scripts location), fix the
path in `docs/lab4-xops-assessment.md` to the real one.

## Part F: Teardown and submit

### 16. Delete the CI stack first (so the docs push does not trigger another run)
```bash
aws cloudformation delete-stack --stack-name northstar-cicd
aws cloudformation wait stack-delete-complete --stack-name northstar-cicd
python3 -c "import boto3;boto3.resource('s3').Bucket('$AB').object_versions.delete()"
aws s3api delete-bucket --bucket "$AB"
aws logs delete-log-group --log-group-name /aws/codebuild/northstar-ci
for A in $(aws sagemaker list-model-packages --model-package-group-name northstar-churn-models --model-approval-status Approved --query 'ModelPackageSummaryList[].ModelPackageArn' --output text); do aws sagemaker update-model-package --model-package-arn $A --model-approval-status Rejected; done
```

### 17. Commit, tag, push
```bash
git add -A && git status --short
git commit -m "Lab 4: evidence and assessment"
git push origin main
git tag lab4-submit && git push origin lab4-submit
git ls-tree -r lab4-submit --name-only | grep -c "docs/lab4"      # expect 9
git ls-remote --tags origin | grep lab4-submit
```
**[HUMAN]** Submit the repo URL in Canvas.

### 18. Tear down Lab 2 and confirm billing stopped
```bash
bash scripts/teardown-lab2.sh
aws ec2 describe-nat-gateways --filter Name=state,Values=available,pending --query 'NatGateways[].NatGatewayId' --output text   # expect empty
aws sagemaker list-mlflow-apps --query 'Summaries[].[Name,Status]' --output text    # confirm MLflow App is gone/stopped
```

## Rubric watch-outs
- The failing-test commit and its revert must both stay in `main` history (no squash/rebase).
- Every path cited in `docs/lab4-xops-assessment.md` must exist at the `lab4-submit` tag.
- Evidence files cannot be regenerated after the stack/log group are deleted: run the audit (step 15) first.
