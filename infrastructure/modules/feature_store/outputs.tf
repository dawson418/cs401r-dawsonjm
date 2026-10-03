output "feature_group_name" {
  description = "Name of the Feature Group"
  value       = aws_sagemaker_feature_group.this.feature_group_name
}

output "feature_group_arn" {
  description = "ARN of the Feature Group"
  value       = aws_sagemaker_feature_group.this.arn
}
