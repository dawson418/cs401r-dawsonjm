output "ml_engineer_role_arn" {
  description = "ARN of the MLEngineer role — later labs pass this to SageMaker"
  value       = aws_iam_role.ml_engineer.arn
}

output "data_engineer_role_arn" {
  description = "ARN of the DataEngineer role - used by Glue jobs, the crawler, and the Feature Group"
  value       = aws_iam_role.data_engineer.arn
}

output "model_monitor_role_arn" {
  description = "ARN of the ModelMonitor role - observes drift runs, writes metrics only"
  value       = aws_iam_role.model_monitor.arn
}