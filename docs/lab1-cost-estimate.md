# Lab 1 Monthly Cost Estimate

Steady-state estimate for the `northstar-dev` environment in `us-east-1`.
Produced using AWS Pricing Calculator (September 2026 public pricing).

| Component | Monthly Estimate | Key Assumptions | One Optimization |
|---|---|---|---|
| SageMaker Studio | $14.40 | 4 hrs/day × 22 working days at $0.164/hr (ml.t3.medium kernel) | Switch to ml.t3.micro ($0.046/hr) for exploration work — saves ~$2.54/month |
| S3 storage (data bucket) | $0.23 | 10 GB at $0.023/GB; four prefixes, minimal objects in Lab 1 | |
| Internet Gateway | $0.10 | ~10 GB outbound data transfer at $0.01/GB for ECR pulls and CloudWatch | |
| DynamoDB (state lock) | $0.00 | On-demand capacity; terraform lock table receives < 100 reads/writes per month, well within free tier | |
| S3 state bucket | $0.01 | < 1 MB state file; versioning enabled adds minimal cost at this size | |
| **Total** | **$14.74** | | |

## Notes

All estimates assume the Studio kernel app is stopped when not in use. If the `ml.t3.medium` kernel runs continuously (730 hrs/month), the SageMaker line rises to $119.72/month and the total to $120.06/month — a 714% increase from the stopped-when-idle baseline.

The VPC itself has no hourly charge. IAM roles, security groups, route tables, and subnets are all free resources.

## Quantified Optimization

Switching the default kernel instance type from `ml.t3.medium` ($0.164/hr) to `ml.t3.micro` ($0.046/hr) for interactive exploration sessions reduces the SageMaker Studio line from $14.40 to $4.05/month at the same 4 hrs/day × 22 days usage pattern — a saving of **$10.35/month (72%)** with no change to training job instance types, which are billed separately per job.