# Lab 5: Security and Privacy Assessment: NorthStar Churn Model

Scope: the churn model and everything it touches in the Lab 1–4 platform: the data bucket (`northstar-dev-data-<account>`), the Feature Store (`northstar-dev-customer-features`), the Model Registry group `northstar-churn-models`, the real-time endpoint `northstar-churn-prod`, and the CI/CD pipeline. IAM roles are the three from the Lab 2 `modules/iam` module: `MLEngineer`, `DataEngineer`, `ModelMonitor`.

## 3a. STRIDE Threat Model

| Threat | STRIDE Category | Likelihood (H/M/L) | Impact (H/M/L) | Mitigation | AWS Control |
|---|---|---|---|---|---|
| An unauthorized caller repeatedly queries `northstar-churn-prod` and uses the scores to infer whether a specific customer was in the training data (membership inference) | Information Disclosure | M | H | Limit who can invoke the endpoint. Keep the endpoint private to IAM principals and do not expose it through a public URL. Rate-limit scoring output to what the offer system needs | IAM: `sagemaker:InvokeEndpoint` granted only to the calling service role. Endpoint is not fronted by API Gateway |
| Someone with access approves a model package that has not passed the metric gates, or swaps the approved version under the registry | Tampering | L | H | Model promotion needs both the CI gates (`tests/test_model.py`, `tests/test_fairness.py`) and a human approval in the CodePipeline `ManualApproval` stage and in the Registry. A failed gate leaves nothing approvable | SageMaker Model Registry approval status plus CodePipeline manual approval action (SNS-notified). Registry changes are logged in CloudTrail |
| Raw customer data or captured inference inputs are read by a principal that should not see them | Information Disclosure | M | H | Keep the bucket private, with public access blocked, versioning on and per-prefix IAM. Data capture writes only to `datacapture/`, which only `MLEngineer` can write | `aws_s3_bucket_public_access_block` on the data bucket; `MLEngineer` (`S3DataCaptureWrite`) limited to `datacapture/*`; `DataEngineer` limited to raw and processed prefixes |
| A training job or the endpoint container is compromised and uses its role to read or change other SageMaker resources | Elevation of Privilege | L | H | Restrict what the execution role can do. The `PassSelfToSageMaker` statement lets `MLEngineer` pass only itself, and only to `sagemaker.amazonaws.com` | IAM `iam:PassRole` with `iam:PassedToService` condition. **Gap:** `MLEngineer` also has `sagemaker:*` on `Resource: "*"`, so a compromised endpoint container with that role can change any SageMaker resource in the account. This is the largest blast radius in the platform |
| Traffic spike or a deliberately expensive request load overloads the endpoint, which stops scoring and keeps billing | Denial of Service | M | M | Target-tracking auto-scaling on invocations per instance (max 2 instances). Rollback alarm on canary p95 latency. Endpoint cost and quota limits | Application Auto Scaling (`SageMakerVariantInvocationsPerInstance`, 1000 per instance); CloudWatch alarm `northstar-churn-rollback-canary-latency`. **Gap:** no per-caller throttling and no WAF or API Gateway in front, so one caller can consume the shared capacity |
| An unexplained change to the endpoint or its data capture settings goes unnoticed | Repudiation | M | M | Keep infrastructure as code (`deployment/configs/`) so every change is a reviewed file in git. Endpoint data capture records what the model saw and returned | Git history on `main`; CloudFormation and Terraform state. **Gap:** CloudTrail management events do not record individual `InvokeEndpoint` calls, so there is no per-caller audit trail for scoring requests. Data capture is the only per-request record |

Two rows map to the Lab 2 roles, and two name gaps those roles do not close:

- **Maps to a role:** the membership-inference row and the S3 disclosure row are both contained by IAM on the roles. Invocation is limited to the calling principal, and capture writes are limited to `datacapture/*` for `MLEngineer`.
- **Gaps the roles do not close:** (1) `MLEngineer` has `sagemaker:*` on all resources, which is wider than the endpoint and training work needs; scoping it to the `northstar-*` resource ARNs would reduce blast radius. (2) `DataEngineer` has `glue:*` on `Resource: "*"`, and there is no network isolation on the endpoint (no `EnableNetworkIsolation`, and no VPC endpoint in the Lab 2 design).

## 3b. Data Classification

| Asset | Tier | Encryption | IAM access policy | Third-party sharing |
|---|---|---|---|---|
| Customer PII (`raw/customers/`: `customer_id`, `state`, `zip_code`, `age_band`, hashed `email`) | Restricted | SSE-S3 today (AES256 on the bucket). Should be SSE-KMS | `DataEngineer` (raw prefix, read and write). `MLEngineer` has no access. Human access only through the data owner's role | No |
| Transaction history (`raw/transactions`, `processed/`) | Restricted | SSE-S3 today. Should be SSE-KMS | `DataEngineer` for raw and processed prefixes. `MLEngineer` has no raw access | No |
| Behavioral clickstream | Confidential | SSE-S3 | Not in the Lab 2 pipeline, so no role grants it. If ingested, `DataEngineer` only | No |
| Product catalog | Internal | SSE-S3 (sufficient: not personal and not sensitive) | Read access for any role that builds features | Yes, under contract |
| Model weights (`artifacts/`, including the Lab 4 XGBoost model) | Confidential | SSE-KMS (see reason below) | `MLEngineer` read and write on `artifacts/*`. `ModelMonitor` read-only | No |
| Inference logs (`datacapture/`) | Restricted | SSE-KMS recommended. Currently SSE-S3 | `MLEngineer` write-only (`S3DataCaptureWrite`). `ModelMonitor` read for monitoring | No |
| Feature Store records (online and offline) | Restricted | Online store uses an AWS-owned key by default. No customer-managed key is configured in this repo | Feature Store access through `MLEngineer` (`features/*`) | No |

**SSE-KMS versus S3-managed (SSE-S3), and why:** S3-managed keys encrypt at rest with no per-key access control, so anyone who can read the object can read it. SSE-KMS adds a key policy, CloudTrail records every `Decrypt` call, and the key can be disabled to cut off access to every object that uses it at once. That matters for Restricted data (PII, transaction history, inference logs) because the owner needs to revoke access without rewriting the data. SSE-S3 is sufficient for Internal data (the product catalog) because the content is not personal. **Current state:** the bucket uses SSE-S3 for everything. Moving the Restricted prefixes to SSE-KMS is an open item.

## 4. Privacy Impact Assessment

**Scope assumption.** The dataset includes Canadian provinces, and GDPR applies only if NorthStar has EU residents as customers. This assessment assumes GDPR applies to the EU subset, and that the same controls are applied to all customers.

### 4.1 Personal data inventory

| Stage | Personal data |
|---|---|
| Raw ingestion (`raw/customers/`, `raw/transactions/`) | `customer_id`, `state`, `zip_code`, `age_band`, hashed `email`, purchase history, `loyalty_tier`, `lifetime_spend` |
| Transform (Glue, `processed/`) | Same fields, with invalid codes cleaned |
| Feature Store (`features/`) | `customer_id`, behavioral features (purchase frequency, spend, basket size), `loyalty_tier`, `churn_label`, `churn_risk_score` |
| Training (SageMaker) | Feature vectors and labels, without `customer_id` (the model input excludes it) |
| Inference (endpoint and `datacapture/`) | Feature vectors per request, captured in JSON Lines. The payload has no `customer_id`, but rows can be joined back by timestamp and order |

### 4.2 Lawful basis

**Choice: legitimate interests (GDPR Art. 6(1)(f)).** Churn prediction uses purchase history that the customer generated while buying from NorthStar, to identify who is likely to stop buying, so that NorthStar can make a retention offer. Customers would expect this from a retailer that holds their loyalty account. The processing is limited: no special-category data, no decision with a legal or similarly significant effect (the score drives an offer, not a refusal), and no sharing with third parties. Under the balancing test, NorthStar's interest in retention outweighs a low privacy impact on the customer. Customers keep the right to object, and an objection must stop retention scoring for that customer.

Consent was not chosen because a churn model would then depend on a per-customer opt-in, and most customers would not give one for a retention model. Contractual necessity was not chosen because scoring is not needed to deliver the loyalty service.

### 4.3 Data minimization

Considered and excluded from the model input (`FEATURE_COLUMNS` in `models/churn/churn_model.py`):
- **Email:** hashed in the source and never used as a feature.
- **`state` and `zip_code`:** location is a quasi-identifier. The model does not need it to predict churn, and the offer system can join location later if needed.
- **`age_band`:** about 8% missing, and age is a sensitive attribute for fairness reasons. Excluded from the model input.
- **`customer_id`:** kept in the Feature Store only as the join key. Excluded from the training and inference input.
- **`churn_date`:** excluded because it leaks the label.

`loyalty_tier` is not a model input, but the fairness check (`tests/test_fairness.py`) still reports recall by tier, so tier-level outcomes are visible. That is a known gap to revisit in Lab 6.

### 4.4 Right to erasure workflow

Request: delete customer `C00123456`. Note: the Lab 1 schema uses the format `CUST-{8 digits}`, so this ID needs to be confirmed against the source system before any deletion runs.

**(a) Raw S3 data.** Find every object under `raw/customers/` and `raw/transactions/` that contains the ID, rewrite each partition without that customer's rows, and then delete all versions. The bucket is versioned, so deleting the current object only hides it. The noncurrent-version expiry from prerequisite 6 must be applied first, or old versions keep the data. **Status: prerequisite 6 is not yet applied.**

**(b) Feature Store.** The online store supports deleting a record by its identifier (`customer_id`). The offline store is an append-only history partitioned by time, so the customer's rows must be removed from each partition that holds them, and the partitions rewritten. Delete the online record first, so the endpoint stops serving the customer's features.

**(c) Training data.** Remove the customer's rows from the feature snapshot the model trained on, then retrain and re-register the model under the approval process in the deployment plan.

**(d) Inference logs.** The captured payloads have no `customer_id`. Find the customer's records by replaying the Feature Store values, which means joining the capture timestamps against the customer's offline feature rows. Then delete the matching objects and all their versions. This step is approximate, and the approach has to be stated to the data protection owner.

**Hardest step: (c), the trained model.** Deleting a customer's rows from the training data does not remove what the model learned from them. The only reliable removal is retraining without the customer, which is a full pipeline run, and even then the new model's weights are not provably free of that customer's influence. Machine unlearning is not reliable enough to rely on here. The second hardest is the offline Feature Store (b): it is an append-only history, so deleting a customer means rewriting partitions, not a delete operation, and the rewrite must not corrupt the time-travel history that training depends on.

## Open items

- Prerequisite 6 (noncurrent-version expiry on `datacapture/`) is not applied. Captured data is hidden at 7 days but kept as old versions until it is added.
- The Restricted prefixes are on SSE-S3. Moving them to SSE-KMS needs a KMS key and a key policy.
- `MLEngineer` `sagemaker:*` on `Resource: "*"` and `DataEngineer` `glue:*` on `Resource: "*"` should be scoped to the `northstar-*` resource ARNs.
- The endpoint has no network isolation. Turning it on would stop the container from making outbound calls, which needs a check against the scoring design first.
