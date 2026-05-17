terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "project_name" {
  description = "Project identifier used in bucket name"
  type        = string
}

variable "retention_days" {
  description = "Object Lock retention in days (K-FSC §31: 1825 = 5 years, SOX: 2555 = 7 years)"
  type        = number
  default     = 1825
}

variable "aws_region" {
  description = "AWS region (KR: ap-northeast-2)"
  type        = string
  default     = "ap-northeast-2"
}

# S3 bucket with Object Lock — COMPLIANCE mode
# COMPLIANCE mode: even root/admin cannot delete within retention period
resource "aws_s3_bucket" "audit" {
  bucket = "${var.project_name}-audit-logs-${data.aws_caller_identity.current.account_id}"

  object_lock_enabled = true

  tags = {
    Purpose    = "audit-log-worm"
    Compliance = "K-FSC,SOX,PCI-DSS"
    ManagedBy  = "sprint-system"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.retention_days
    }
  }
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "audit" {
  bucket                  = aws_s3_bucket.audit.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# IAM role for GitHub Actions OIDC — write-only to audit bucket
resource "aws_iam_role" "audit_writer" {
  name = "${var.project_name}-sprint-audit-writer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*"
        }
      }
    }]
  })
}

variable "github_org"  { type = string }
variable "github_repo" { type = string }

resource "aws_iam_role_policy" "audit_writer" {
  name = "audit-write-only"
  role = aws_iam_role.audit_writer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Write audit logs
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.audit.arn}/audit-logs/*"
      },
      {
        # List to verify upload (not read content)
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.audit.arn
        Condition = {
          StringLike = { "s3:prefix" = "audit-logs/*" }
        }
      }
    ]
  })
}

# IAM role for auditors — read-only
resource "aws_iam_role" "audit_reader" {
  name = "${var.project_name}-sprint-audit-reader"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "audit_reader" {
  name = "audit-read-only"
  role = aws_iam_role.audit_reader.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket", "s3:GetObjectRetention", "s3:GetObjectLegalHold"]
      Resource = [aws_s3_bucket.audit.arn, "${aws_s3_bucket.audit.arn}/*"]
    }]
  })
}

data "aws_caller_identity" "current" {}

output "audit_bucket_name" {
  value = aws_s3_bucket.audit.id
}

output "audit_writer_role_arn" {
  value = aws_iam_role.audit_writer.arn
}

output "audit_reader_role_arn" {
  value = aws_iam_role.audit_reader.arn
}
