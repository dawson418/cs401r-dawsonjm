# ── modules/glue ─────────────────────────────────────────────────────────────
# Catalog database, raw crawler, VPC connection, and the transform ETL job.
# Task 3 adds the feature-engineer job to this same module.

locals {
  name_prefix = "${var.project}-${var.environment}"
}

resource "aws_glue_catalog_database" "this" {
  name = "${var.project}_${var.environment}"
}

# Without an explicit classifier the crawler can fail to detect the header row
# (every column looks like a string) and name the columns col0, col1, ...
resource "aws_glue_classifier" "csv_with_header" {
  name = "${local.name_prefix}-csv-header"

  csv_classifier {
    contains_header = "PRESENT"
    delimiter       = ","
    quote_symbol    = "\""
  }
}

resource "aws_glue_crawler" "raw" {
  name          = "${local.name_prefix}-raw-crawler"
  database_name = aws_glue_catalog_database.this.name
  role          = var.role_arn
  classifiers   = [aws_glue_classifier.csv_with_header.name]

  s3_target {
    path = "s3://${var.bucket_name}/${var.raw_prefix}"
  }
}

# NETWORK connection: this is what places Glue workers in the private subnet.
resource "aws_glue_connection" "vpc" {
  name            = "${local.name_prefix}-vpc-connection"
  connection_type = "NETWORK"

  physical_connection_requirements {
    availability_zone      = var.availability_zone
    security_group_id_list = [var.security_group_id]
    subnet_id              = var.subnet_id
  }
}

resource "aws_s3_object" "transform_script" {
  bucket = var.bucket_name
  key    = "${var.script_prefix}${basename(var.transform_script_path)}"
  source = var.transform_script_path
  etag   = filemd5(var.transform_script_path)
}

resource "aws_glue_job" "transform" {
  name              = "${local.name_prefix}-transform"
  role_arn          = var.role_arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 30
  max_retries       = 0
  connections       = [aws_glue_connection.vpc.name]

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${var.bucket_name}/${aws_s3_object.transform_script.key}"
  }

  default_arguments = {
    "--job-language"  = "python"
    "--database_name" = aws_glue_catalog_database.this.name
    "--table_name"    = var.table_name
    "--output_path"   = "s3://${var.bucket_name}/${var.processed_prefix}"
  }
}

resource "aws_s3_object" "feature_engineer_script" {
  bucket = var.bucket_name
  key    = "${var.script_prefix}${basename(var.feature_script_path)}"
  source = var.feature_script_path
  etag   = filemd5(var.feature_script_path)
}

resource "aws_glue_job" "feature_engineer" {
  name              = "${local.name_prefix}-feature-engineer"
  role_arn          = var.role_arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 60
  max_retries       = 0
  connections       = [aws_glue_connection.vpc.name]

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${var.bucket_name}/${aws_s3_object.feature_engineer_script.key}"
  }

  default_arguments = {
    "--job-language"       = "python"
    "--input_path"         = "s3://${var.bucket_name}/${var.processed_prefix}"
    "--output_path"        = "s3://${var.bucket_name}/${var.features_prefix}"
    "--feature_group_name" = var.feature_group_name
    "--region"             = var.region
  }
}
