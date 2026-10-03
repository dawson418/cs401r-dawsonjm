# cs401r-lab1-template
CS 401R Lab 1: Platform Foundation — starter template (do not fork directly)

---

## Lab 2: Data & Feature Engineering

Lab 2 extends the Lab 1 platform in two directions: it hardens the infrastructure (private networking, more IAM roles, S3 lifecycle rules) and adds a data pipeline that turns raw customer transactions into labeled churn features in SageMaker Feature Store. Everything is Terraform.

### What changed in existing modules

| Module | Lab 2 change |
|--------|--------------|
| `modules/vpc/` | Private subnet `10.0.1.0/24`, Elastic IP, NAT Gateway (in the public subnet), private route table (`0.0.0.0/0` to NAT), and a self-referencing all-ports ingress rule on the security group (Glue requires it). `enable_nat_gateway` toggles the NAT, EIP, and default route (false in LocalStack). New output: `private_subnet_id`. |
| `modules/storage/` | S3 lifecycle configuration with five rules (`expire-raw-data`, `expire-raw-versions`, `expire-processed-versions`, `expire-feature-versions`, `expire-datacapture`), toggled by `enable_lifecycle_rules`. `force_destroy` variable (true in dev) so teardown can delete a versioned bucket. |
| `modules/iam/` | Two new roles with policies and attachments: `DataEngineer` (trusted by Glue, Lambda, and SageMaker; writes `raw/`, `processed/`, `features/`; read-only on `artifacts/glue/`; cannot write `artifacts/`) and `ModelMonitor` (read-only on `artifacts/`, CloudWatch metrics and alarms only). |
| `modules/sagemaker/` | Domain moved to the private subnet with `app_network_access_type = "VpcOnly"`, so Studio traffic goes out through the NAT Gateway. |

### New modules

- **`modules/glue/`**: catalog database `northstar_dev`, a CSV classifier (header present), the crawler `northstar-dev-raw-crawler` on `raw/customers/`, a Glue `NETWORK` connection in the private subnet, and two Spark jobs (Glue 4.0): `northstar-dev-transform` and `northstar-dev-feature-engineer`. The job scripts in `glue-scripts/` are uploaded to `artifacts/glue/` by Terraform.
- **`modules/feature_store/`**: Feature Group `northstar-dev-customer-features` with 16 feature definitions (2 keys, 13 features, 1 label), online store enabled, and an offline store at `features/offline-store/`. `event_time` is Fractional (Unix epoch seconds).

### Data pipeline

```
raw/customers/ (CSV)
  -> Glue crawler -> catalog table northstar_dev.customers
  -> transform job -> processed/customers/ (Parquet, one row per transaction)
  -> feature-engineer job -> features/customers/ (Parquet, one row per customer)
                          -> Feature Store (PutRecord)
```

- **Transform** (`glue-scripts/transform.py`): trims whitespace, parses mixed date formats, casts types, drops rows with no `customer_id`, imputes numeric nulls with the median and string nulls with `unknown`, and deduplicates on `transaction_id`. The grain stays transaction-level.
- **Feature engineering** (`glue-scripts/feature_engineer.py`): splits each customer's timeline at `FEATURE_CUTOFF` (2026-04-01). The 13 features come only from purchases on or before that date; `churn_label` is 1 if the customer made no purchase in the following window ending 2026-06-30. Every window is anchored to the cutoff, never to today's date or the data's maximum date, so there is no label leakage.
- The data contract for `processed/customers/` is in `docs/lab2-data-contract.md`, and the lineage diagram is `docs/lab2-data-lineage.png`.

### Running it end to end

Prerequisites: AWS credentials configured, `northstar-raw-sample.csv` from the Lab 2 starter kit in the repo root.

```bash
# 1. Build the infrastructure (about 15 minutes; the SageMaker domain is the slow part)
cd infrastructure/environments/dev
terraform init
terraform apply -no-color 2>&1 | tee -a ../../../docs/lab2-extend-output.txt
cd ../../..

# 2. Land the raw data
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws s3 cp northstar-raw-sample.csv s3://northstar-dev-data-$ACCOUNT/raw/customers/northstar-raw-sample.csv

# 3. Crawl it (start-crawler returns immediately, so poll until READY)
aws glue start-crawler --name northstar-dev-raw-crawler
until [ "$(aws glue get-crawler --name northstar-dev-raw-crawler --query 'Crawler.State' --output text)" = "READY" ]; do sleep 15; done

# 4. Run the two jobs, in order
aws glue start-job-run --job-name northstar-dev-transform
#    wait for SUCCEEDED (aws glue get-job-runs --job-name northstar-dev-transform --query 'JobRuns[0].JobRunState')
aws glue start-job-run --job-name northstar-dev-feature-engineer
#    wait for SUCCEEDED, then check one record:
aws sagemaker-featurestore-runtime get-record \
  --feature-group-name northstar-dev-customer-features \
  --record-identifier-value-as-string <a customer_id from features/customers/>

# 5. Verify everything
bash scripts/verify-lab2.sh 2>&1 | tee docs/lab2-verify-output.txt
```

Expected results: about 157,600 processed rows across 9,999 customers; 9,999 feature rows with a churn rate near 22 percent; all four loyalty tiers present; 9,999 records in the Feature Store. The offline store lags the online store by roughly 15 minutes.

LocalStack validation (no NAT Gateway, no lifecycle rules, no SageMaker):

```bash
make local-validate LOCAL_OUT=docs/lab2-localstack-output.txt
```

### Teardown

The NAT Gateway bills about $0.045 per hour while it exists. After capturing evidence:

```bash
bash scripts/teardown-lab2.sh 2>&1 | tee docs/lab2-destroy-output.txt
```

`terraform destroy` alone is not enough: Glue network interfaces, the Studio EFS filesystem, SageMaker-created security groups, S3 object versions, the `sagemaker_featurestore` Glue database, and SageMaker lineage artifacts all live outside Terraform's state. The script removes them in order and then checks that no billable resource remains.

### Evidence files

| File | Contents |
|------|----------|
| `docs/lab2-extend-output.txt` | Every `terraform apply` for this lab, appended in order |
| `docs/lab2-localstack-output.txt` | LocalStack validation: 3 IAM roles, VPC, no NAT |
| `docs/lab2-verify-output.txt` | Output of `scripts/verify-lab2.sh` against the live stack |
| `docs/lab2-data-contract.md` | Data contract for `processed/customers/` |
| `docs/lab2-data-lineage.png` | Lineage diagram with formats and IAM roles |
| `docs/lab2-destroy-output.txt` | Clean teardown evidence (committed to `main` after tagging) |
