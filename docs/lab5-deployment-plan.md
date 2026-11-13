# Lab 5: Deployment Plan: NorthStar Churn Model

Run everything from the repo root. Account `649249221429`, region `us-east-1`.

## 1. Deployment strategy and rationale

**Strategy: real-time endpoint with a 9:1 canary** (champion 90%, canary 10%), on one endpoint, `northstar-churn-prod`.

Rationale: retention offers are generated when a customer interacts with NorthStar, so the churn score is needed per customer, on demand. A real-time endpoint serves that. A nightly batch job would be cheaper, but it would score customers whose behavior has changed since the last run.

*Assumption to confirm with the offers team:* this rationale holds only if offers need same-day scores. If they need only a nightly list, use the Batch Transform parallel-run path instead.

*Limit of this lab run:* only v3 is approved, so the champion and the canary both serve v3. This run tests the traffic split, the alarm, and the rollback. It does not compare two models. A production canary needs an approved champion to compare against.

A direct swap of the endpoint config was rejected. It would send 100% of traffic to a model we have not watched in production, and a bad model would reach every customer before anyone noticed.

## 2. Pre-deployment checklist

Every item must be true before step 3 starts.

1. **Model approved by a named person.** Model Registry package `northstar-churn-models/3` is `Approved`. Approver: Dawson Martin, model owner, on 2026-11-12. Metrics at approval: precision@top10% 0.7067, recall@top10% 0.3212, AUC 0.7714, lift CI 0.0193 to 0.0562 (excludes zero).
2. **CI gates green** on the commit that produced the model: build `6daaddf9` on commit `11334c5`, with the regression test passing.
3. **Fairness flag acknowledged.** The build reports a recall gap of 32.2 points between bronze and gold. The approver has read it, and it is accepted for the canary only.
4. **Capacity.** The `ml.m5.large` endpoint quota is 30 (`L-614B09FD`). Scaling is registered with max 2 instances.
5. **Data capture writable.** The `S3DataCaptureWrite` statement is applied to the MLEngineer policy.
6. **Config files reviewed** in `deployment/configs/`.

## 3. Deployment steps

```bash
# 3a. Model from the approved package
ROLE=$(terraform -chdir=infrastructure/environments/dev output -raw ml_engineer_role_arn)
aws sagemaker create-model --model-name northstar-churn-v3 --execution-role-arn "$ROLE" \
  --primary-container ModelPackageName=arn:aws:sagemaker:us-east-1:649249221429:model-package/northstar-churn-models/3

# 3b. Endpoint config with both variants and data capture
aws sagemaker create-endpoint-config --cli-input-json file://deployment/configs/endpoint-config-canary.json

# 3c. Endpoint (about 7 minutes)
aws sagemaker create-endpoint --endpoint-name northstar-churn-prod --endpoint-config-name northstar-churn-canary-config
aws sagemaker wait endpoint-in-service --endpoint-name northstar-churn-prod

# 3d. Auto-scaling and rollback alarm
aws application-autoscaling register-scalable-target --cli-input-json file://deployment/configs/scalable-target.json
aws application-autoscaling put-scaling-policy --cli-input-json file://deployment/configs/scaling-policy.json
aws cloudwatch put-metric-alarm --cli-input-json file://deployment/configs/rollback-alarm.json
```

## 4. Rollback criteria

- **Metric:** `ModelLatency`, p95, for the `canary` variant, in microseconds.
- **Threshold:** above **200000** (200 ms) for **2** consecutive 1-minute periods.
- **Alarm:** `northstar-churn-rollback-canary-latency`. It must match `deployment/configs/rollback-alarm.json`, which uses `Threshold: 200000`, `Unit: Microseconds`.
- **Action:** `bash deployment/configs/rollback-action.sh` sets the canary to weight 0.
- **Decision owner:** the on-call ML engineer rolls back when the alarm fires. The model owner is notified and decides whether to re-deploy.

Units matter. A threshold of `200` would be 0.2 ms, below normal latency, and would roll back a healthy deployment.

## 5. Monitoring window

- **Production plan: 48 hours** at 10% canary before promotion.
- **Lab execution: 60 minutes**, then promote or roll back.

What the 60 minutes cannot catch, and what the 48 hours should:

- **Daily and weekly patterns.** Traffic and purchase behavior vary by day of week. A 60-minute window samples one slice.
- **Slow failures.** Memory growth, connection leaks, and scaling lag appear over hours.
- **Business outcome.** The churn label is defined over the 90 days after the snapshot, so model quality cannot be measured in 48 hours or 60 minutes. Only latency, errors, and score distributions are observable that fast.

Clean deployment means: no alarm in ALARM, no endpoint errors (`Invocation5XXErrors`), canary score distribution within the range seen in the offline evaluation, and the observed split within a few points of 9:1.

## 6. Stakeholder notifications

| Stage | Notified role | What they receive |
|---|---|---|
| Deployment starts | Offers team lead, on-call engineer | Start time, model version, rollback criteria |
| Canary live | Data protection officer | Confirmation that data capture is enabled and where it writes |
| Promotion to 100% | Offers team lead, model owner | Metrics over the window, confirmation of the promotion |
| Rollback | Model owner, offers team lead, on-call engineer | Alarm name, time, weights before and after |

Roles, not individuals, receive these. The CodePipeline approval topic `northstar-model-approvals` sends the approval request to whoever subscribes it.

## 7. Post-deployment review and cleanup

**Review:** seven days after promotion, led by the model owner, with the offers team lead, the data protection officer, and the on-call engineer. The artifact is a one-page review: alarms fired, rollbacks, score drift, and the first measurable churn outcomes.

**Cleanup, in order:**

1. Deregister the scalable target and delete its policy (the endpoint deletion also does this).
2. Delete the rollback alarm.
3. Delete the endpoint, then the endpoint config, then the model.
4. Verify with `bash scripts/teardown-lab5.sh`. It writes `docs/lab5-teardown-output.txt`, and all counts must read `0`.

Once the endpoint is deleted, billing stops. Rolling back to weight 0 does not stop it, because the instance keeps running.
