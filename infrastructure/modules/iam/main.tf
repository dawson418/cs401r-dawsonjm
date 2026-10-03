# ── modules/iam ──────────────────────────────────────────────────────────────
# Required resources (Task B1). Exactly one of each:
#
#   aws_iam_role                     MLEngineer, trusted by sagemaker.amazonaws.com
#   aws_iam_policy
#   aws_iam_role_policy_attachment
#
# Least privilege is graded in later labs, so start narrow: grant only the S3
# prefixes and SageMaker actions this role actually needs. A wildcard policy
# here will cost you points in Lab 2.

resource "aws_iam_role" "ml_engineer" {
  name = "${var.project}-${var.environment}-MLEngineer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "sagemaker.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${var.project}-${var.environment}-MLEngineer"
  }
}

resource "aws_iam_policy" "ml_engineer" {
  name = "${var.project}-${var.environment}-MLEngineer-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sagemaker:*"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.bucket_name}/features/*",
          "arn:aws:s3:::${var.bucket_name}/artifacts/*",
          "arn:aws:s3:::${var.bucket_name}"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:GetAuthorizationToken"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ml_engineer" {
  role       = aws_iam_role.ml_engineer.name
  policy_arn = aws_iam_policy.ml_engineer.arn
}

# ---- DataEngineer: Glue jobs, crawler, Feature Store writer ----------------

resource "aws_iam_role" "data_engineer" {
  name = "${var.project}-${var.environment}-DataEngineer"

  # sagemaker.amazonaws.com is required or CreateFeatureGroup rejects the role
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = [
            "glue.amazonaws.com",
            "lambda.amazonaws.com",
            "sagemaker.amazonaws.com"
          ]
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${var.project}-${var.environment}-DataEngineer"
  }
}

resource "aws_iam_policy" "data_engineer" {
  name = "${var.project}-${var.environment}-DataEngineer-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "GlueFullAccess"
        Effect   = "Allow"
        Action   = ["glue:*", "glue:GetConnection"]
        Resource = "*"
      },
      {
        # Glue creates, tags, and deletes ENIs for jobs running in the VPC
        Sid    = "GlueVpcNetworkInterfaces"
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DeleteNetworkInterface",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeVpcs",
          "ec2:DescribeVpcEndpoints",
          "ec2:DescribeSubnets",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeRouteTables"
        ]
        Resource = "*"
      },
      {
        Sid      = "GlueEniTagging"
        Effect   = "Allow"
        Action   = ["ec2:CreateTags", "ec2:DeleteTags"]
        Resource = "arn:aws:ec2:*:*:network-interface/*"
      },
      {
        Sid    = "DataPrefixesReadWrite"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [
          "arn:aws:s3:::${var.bucket_name}/raw/*",
          "arn:aws:s3:::${var.bucket_name}/processed/*",
          "arn:aws:s3:::${var.bucket_name}/features/*"
        ]
      },
      {
        # Feature Store offline store writes objects with an ACL
        Sid      = "FeatureStoreObjectAcl"
        Effect   = "Allow"
        Action   = ["s3:PutObjectAcl"]
        Resource = "arn:aws:s3:::${var.bucket_name}/features/*"
      },
      {
        # Feature Store checks the bucket ACL before accepting the offline store
        Sid      = "BucketLevel"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketAcl"]
        Resource = "arn:aws:s3:::${var.bucket_name}"
      },
      {
        # Glue fetches its own job scripts here; read-only, no write on artifacts/
        Sid      = "GlueScriptsReadOnly"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::${var.bucket_name}/artifacts/glue/*"
      },
      {
        Sid    = "FeatureStore"
        Effect = "Allow"
        Action = [
          "sagemaker:PutRecord",
          "sagemaker:CreateFeatureGroup",
          "sagemaker:DescribeFeatureGroup"
        ]
        Resource = "*"
      },
      {
        Sid    = "LogsWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "data_engineer" {
  role       = aws_iam_role.data_engineer.name
  policy_arn = aws_iam_policy.data_engineer.arn
}

# ---- ModelMonitor: observes, never acts -------------------------------------

resource "aws_iam_role" "model_monitor" {
  name = "${var.project}-${var.environment}-ModelMonitor"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "sagemaker.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${var.project}-${var.environment}-ModelMonitor"
  }
}

resource "aws_iam_policy" "model_monitor" {
  name = "${var.project}-${var.environment}-ModelMonitor-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchMetricsAndAlarms"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DescribeAlarms"
        ]
        Resource = "*"
      },
      {
        Sid      = "ProcessingJobVisibility"
        Effect   = "Allow"
        Action   = ["sagemaker:ListProcessingJobs", "sagemaker:DescribeProcessingJob"]
        Resource = "*"
      },
      {
        Sid    = "ArtifactsReadOnly"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.bucket_name}",
          "arn:aws:s3:::${var.bucket_name}/artifacts/*"
        ]
      },
      {
        Sid    = "LogsWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "model_monitor" {
  role       = aws_iam_role.model_monitor.name
  policy_arn = aws_iam_policy.model_monitor.arn
}