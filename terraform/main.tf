terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
    }
  }
}

# ── S3 Bucket for Dashboard Data ─────────────────────────────────────────────
# This bucket stores the aggregated dashboard JSON data.
# The backoffice.html itself is deployed to each target domain's existing bucket.

resource "aws_s3_bucket" "dashboard_data" {
  bucket_prefix = "${var.project_name}-data-"
}

resource "aws_s3_bucket_versioning" "dashboard_data" {
  bucket = aws_s3_bucket.dashboard_data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "dashboard_data" {
  bucket = aws_s3_bucket.dashboard_data.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "dashboard_data" {
  bucket = aws_s3_bucket.dashboard_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "dashboard_data" {
  bucket = aws_s3_bucket.dashboard_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "data_bucket" {
  value = aws_s3_bucket.dashboard_data.id
}

output "data_bucket_arn" {
  value = aws_s3_bucket.dashboard_data.arn
}
