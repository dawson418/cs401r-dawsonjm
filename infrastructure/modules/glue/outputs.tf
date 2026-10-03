output "database_name" {
  description = "Name of the Glue catalog database"
  value       = aws_glue_catalog_database.this.name
}

output "crawler_name" {
  description = "Name of the raw-data crawler"
  value       = aws_glue_crawler.raw.name
}

output "transform_job_name" {
  description = "Name of the transform ETL job"
  value       = aws_glue_job.transform.name
}

output "connection_name" {
  description = "Name of the Glue NETWORK connection (reused by the feature-engineer job)"
  value       = aws_glue_connection.vpc.name
}

output "feature_engineer_job_name" {
  description = "Name of the feature-engineer ETL job"
  value       = aws_glue_job.feature_engineer.name
}
