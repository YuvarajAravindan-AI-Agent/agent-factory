variable "region" { default = "us-east-1" }
variable "profile" { default = "enterprises" }
variable "name" { default = "af" }
variable "notify_email" {
  description = "Where approval requests are emailed (SNS asks this address to confirm once)."
  default     = "founder@ai-agentic-enterprises.com"
}
variable "gateway_url" { default = "https://vertex-gateway-714593281128.us-central1.run.app" }
variable "gateway_token_secret" { default = "agent-factory/vertex-gateway-token" }
variable "agent_package" {
  description = "Zip built by scripts/package_agent.sh"
  default     = "../build/agent.zip"
}

data "aws_caller_identity" "me" {}
data "aws_partition" "p" {}

locals {
  acct   = data.aws_caller_identity.me.account_id
  bucket = "${var.name}-workspace-${local.acct}"
}

# The secret is created outside Terraform (scripts/setup-gateway-token.sh) so its value never
# lands in Terraform state.
data "aws_secretsmanager_secret" "gateway" { name = var.gateway_token_secret }

# ---------------------------------------------------------------- workspace bucket
resource "aws_s3_bucket" "ws" {
  bucket        = local.bucket
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "ws" {
  bucket                  = aws_s3_bucket.ws.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ws" {
  bucket = aws_s3_bucket.ws.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "ws" {
  bucket = aws_s3_bucket.ws.id
  rule {
    id     = "expire-runs"
    status = "Enabled"
    filter { prefix = "runs/" }
    expiration { days = 30 }
  }
  rule {
    id     = "expire-build-logs"
    status = "Enabled"
    filter { prefix = "codebuild-logs/" }
    expiration { days = 30 }
  }
}

resource "aws_s3_bucket_policy" "ws_tls" {
  bucket = aws_s3_bucket.ws.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.ws.arn, "${aws_s3_bucket.ws.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# ---------------------------------------------------------------- notifications
resource "aws_sns_topic" "approvals" { name = "${var.name}-approvals" }

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.approvals.arn
  protocol  = "email"
  endpoint  = var.notify_email
}

output "bucket" { value = aws_s3_bucket.ws.bucket }
