# modules/feature_store
# One Feature Group with the online store enabled and an S3 offline store.
#
# Creating it fails with misleading errors if the execution role is wrong:
#   "execution role ARN is invalid"  -> role trust policy lacks sagemaker.amazonaws.com
#   "Invalid S3Uri provided"         -> role lacks s3:GetBucketAcl on the bucket
# Both are already handled in modules/iam.

resource "aws_sagemaker_feature_group" "this" {
  feature_group_name             = "${var.project}-${var.environment}-customer-features"
  record_identifier_feature_name = var.record_identifier_name
  event_time_feature_name        = var.event_time_name
  role_arn                       = var.role_arn

  dynamic "feature_definition" {
    for_each = var.feature_definitions
    content {
      feature_name = feature_definition.value.name
      feature_type = feature_definition.value.type
    }
  }

  online_store_config {
    enable_online_store = true
  }

  offline_store_config {
    s3_storage_config {
      s3_uri = "s3://${var.bucket_name}/${var.offline_store_prefix}"
    }
  }

  tags = {
    Name = "${var.project}-${var.environment}-customer-features"
  }
}
