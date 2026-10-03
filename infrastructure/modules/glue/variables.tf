variable "project" {
  description = "Project name, used as the first element of every resource name"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "bucket_name" {
  description = "Name of the data bucket holding raw/, processed/, features/, and artifacts/"
  type        = string
}

variable "role_arn" {
  description = "ARN of the DataEngineer role used by the crawler and the ETL jobs"
  type        = string
}

variable "subnet_id" {
  description = "Private subnet the Glue workers run in (via the NETWORK connection)"
  type        = string
}

variable "security_group_id" {
  description = "Security group attached to the Glue NETWORK connection; must have a self-referencing all-ports ingress rule"
  type        = string
}

variable "availability_zone" {
  description = "Availability Zone of the private subnet"
  type        = string
}

variable "transform_script_path" {
  description = "Local path to the transform.py Glue script that is uploaded to S3"
  type        = string
}

variable "table_name" {
  description = "Catalog table the crawler creates (named after the last element of the raw prefix)"
  type        = string
  default     = "customers"
}

variable "raw_prefix" {
  description = "S3 prefix the crawler scans"
  type        = string
  default     = "raw/customers/"
}

variable "processed_prefix" {
  description = "S3 prefix the transform job writes Parquet to"
  type        = string
  default     = "processed/customers/"
}

variable "script_prefix" {
  description = "S3 prefix Glue job scripts are uploaded to"
  type        = string
  default     = "artifacts/glue/"
}

variable "feature_script_path" {
  description = "Local path to the feature_engineer.py Glue script that is uploaded to S3"
  type        = string
}

variable "features_prefix" {
  description = "S3 prefix the feature-engineer job writes Parquet to (separate from the Feature Store offline store prefix)"
  type        = string
  default     = "features/customers/"
}

variable "feature_group_name" {
  description = "Name of the SageMaker Feature Group the feature-engineer job ingests into"
  type        = string
}

variable "region" {
  description = "AWS region for the Feature Store runtime client used by the feature-engineer job"
  type        = string
}
