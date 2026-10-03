variable "project" {
  description = "Project name, used as the first element of every resource name"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "bucket_name" {
  description = "Name of the data bucket that backs the offline store"
  type        = string
}

variable "role_arn" {
  description = "ARN of the execution role for the Feature Group (DataEngineer; its trust policy must include sagemaker.amazonaws.com)"
  type        = string
}

variable "offline_store_prefix" {
  description = "S3 prefix for the offline store; keep it separate from the feature job's own output prefix"
  type        = string
  default     = "features/offline-store/"
}

variable "record_identifier_name" {
  description = "Name of the record identifier feature"
  type        = string
  default     = "customer_id"
}

variable "event_time_name" {
  description = "Name of the event time feature (must be declared Fractional and written as epoch seconds)"
  type        = string
  default     = "event_time"
}

variable "feature_definitions" {
  description = "Feature Group schema: 2 keys, 13 features, 1 label"
  type = list(object({
    name = string
    type = string
  }))
  default = [
    { name = "customer_id", type = "String" },
    { name = "event_time", type = "Fractional" },
    { name = "days_since_last_purchase", type = "Fractional" },
    { name = "customer_tenure_days", type = "Fractional" },
    { name = "purchase_frequency_30d", type = "Fractional" },
    { name = "purchase_frequency_90d", type = "Fractional" },
    { name = "purchase_frequency_180d", type = "Fractional" },
    { name = "avg_order_value", type = "Fractional" },
    { name = "total_spend_90d", type = "Fractional" },
    { name = "total_lifetime_value", type = "Fractional" },
    { name = "avg_basket_size_6m", type = "Fractional" },
    { name = "category_diversity_score", type = "Fractional" },
    { name = "online_to_store_ratio", type = "Fractional" },
    { name = "loyalty_tier", type = "String" },
    { name = "churn_risk_score", type = "Fractional" },
    { name = "churn_label", type = "Integral" },
  ]
}
