## ADR-001: NorthStar Platform Foundation

### Status
Accepted

### Context
NorthStar Retail is building a shared AI platform that will serve three concurrent workstreams: a customer churn scoring pipeline, an LLM-based product recommendation serving layer, and a demand forecasting system. All three share training infrastructure and model artifacts but have different data access patterns and latency requirements. From day one, the platform needs an identity model that enforces workstream isolation — a churn scoring job must not be able to read recommendation serving logs, and neither should be able to overwrite raw ingestion data. It also needs a storage tier structure that separates raw source data from processed features and trained artifacts, because Lab 2 introduces a DataEngineer role that owns the ingestion layer while the MLEngineer role owns the feature and artifact layers. Defining these boundaries now avoids a refactor when the second role arrives.

### Decision
The platform runs inside a single VPC (`northstar-dev-vpc`, `10.0.0.0/16`) in `us-east-1a` with one public subnet (`10.0.100.0/24`) in Lab 1. The public subnet hosts the SageMaker Studio domain. A dedicated security group (`northstar-dev-sagemaker-sg`) restricts inbound traffic to the VPC CIDR, preventing Studio from accepting connections from outside the VPC boundary while still allowing outbound access for pulling ECR images and writing CloudWatch logs.

S3 uses a single bucket (`northstar-dev-data-{account-id}`) with four prefixes: `raw/`, `processed/`, `features/`, and `artifacts/`. The split is driven by the NorthStar role model: the MLEngineer IAM role has read/write access only to `features/` and `artifacts/`, and is explicitly denied `raw/` and `processed/` by omission. This means a misconfigured training job cannot overwrite source data, which is a hard requirement when the churn scoring pipeline reads from the same bucket as the LLM fine-tuning pipeline. Versioning is enabled on the bucket so that accidental overwrites to `features/` are recoverable without a full reingestion run.

The MLEngineer IAM role uses a least-privilege policy scoped to SageMaker operations, S3 access on `features/` and `artifacts/` only, CloudWatch Logs write, and ECR read. The trust policy allows only `sagemaker.amazonaws.com` to assume the role, so no human user or EC2 instance can assume it directly. This is necessary because the LLM serving layer will eventually run inference jobs under this same role, and a broad trust policy would allow lateral movement between workstreams.

### Consequences

#### What this makes easy
- Adding the DataEngineer role in Lab 2 requires no changes to the VPC or bucket structure — the prefixes and IAM boundary already exist.
- Running `terraform destroy` completes cleanly in under 90 seconds because the SageMaker domain is configured with `home_efs_file_system = "Delete"`, which prevents the EFS mount target from pinning the subnet.
- The single-bucket four-prefix design means the churn scoring and LLM pipelines share one S3 endpoint, eliminating cross-bucket data transfer costs between workstreams.

#### What this makes harder
- The public subnet has no NAT Gateway, so any future private subnet resource (a training cluster that should not have a public IP) requires Lab 2's networking additions before it can reach S3 or ECR.
- A single `us-east-1a` availability zone means a zonal failure takes down all Studio sessions simultaneously. Acceptable for a development environment but not for the eventual serving layer.
- The MLEngineer policy uses `sagemaker:*`, which is broader than necessary and will need to be tightened before production to satisfy a least-privilege audit.

#### What would cause you to revisit this decision
- If NorthStar adds a fourth workstream (such as a real-time feature store) that requires sub-millisecond S3 access patterns, the prefix-based isolation model may need to split into separate buckets with VPC endpoints.
- If the LLM serving layer requires a private subnet with a NAT Gateway for security compliance, the single public subnet design needs to be replaced.

### Alternative Considered
The alternative was to create one S3 bucket per workstream (a churn bucket, an LLM bucket, a forecasting bucket) rather than one bucket with prefixes. This would give each workstream a hard IAM boundary at the bucket level and make cross-workstream access impossible to grant accidentally. It was rejected because NorthStar's three systems share training infrastructure — the SageMaker domain writes artifacts from all three pipelines — and routing artifact writes to three different buckets would require the MLEngineer role to hold three separate bucket ARNs in its policy, complicating Lab 2's DataEngineer handoff and making the Terraform module less reusable. The prefix approach achieves the same access isolation with a simpler IAM policy surface.

### AWS Service Selection
- **Networking isolation model**: VPC with a public subnet and security group, chosen because SageMaker Studio requires VPC placement and the security group's VPC-CIDR-only ingress rule enforces workstream network isolation without a more expensive transit gateway.
- **Storage design**: Single S3 bucket with four prefixes and versioning, chosen because the NorthStar role model requires intra-bucket access boundaries that IAM prefix-level conditions enforce more cheaply than separate buckets with separate policies.
- **Identity model**: IAM role with a scoped inline policy and SageMaker-only trust, chosen because the churn scoring and LLM serving pipelines must run under a non-human principal that cannot be assumed by EC2 or Lambda without an explicit trust extension.
- **ML development environment**: SageMaker Studio on `ml.t3.medium`, chosen because Studio provides a managed JupyterLab environment that shares the VPC and IAM role context with training jobs, eliminating a separate notebook-to-cluster authentication layer for the three NorthStar workstreams.