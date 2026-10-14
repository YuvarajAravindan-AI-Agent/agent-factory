# Two-stage build sandbox.
#  af-deps : has internet, downloads wheels only (--only-binary, so no package code runs).
#  af-test : runs the generated code and its tests inside a VPC with NO internet route;
#            the only egress is the S3 gateway endpoint (to fetch source/wheels, write logs).

data "aws_availability_zones" "az" { state = "available" }

resource "aws_vpc" "sandbox" {
  cidr_block           = "10.42.0.0/24"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${var.name}-build-sandbox" }
}

resource "aws_subnet" "sandbox" {
  vpc_id            = aws_vpc.sandbox.id
  cidr_block        = "10.42.0.0/26"
  availability_zone = data.aws_availability_zones.az.names[0]
  tags              = { Name = "${var.name}-build-sandbox-private" }
}

# No internet gateway, no NAT: this route table only knows the VPC and S3.
resource "aws_route_table" "sandbox" {
  vpc_id = aws_vpc.sandbox.id
  tags   = { Name = "${var.name}-build-sandbox-rt" }
}

resource "aws_route_table_association" "sandbox" {
  subnet_id      = aws_subnet.sandbox.id
  route_table_id = aws_route_table.sandbox.id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.sandbox.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.sandbox.id]
  # Only this account's workspace bucket is reachable through the endpoint.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = "*"
      Action    = ["s3:GetObject", "s3:PutObject", "s3:GetBucketLocation", "s3:GetBucketAcl", "s3:GetObjectVersion"]
      Resource  = [aws_s3_bucket.ws.arn, "${aws_s3_bucket.ws.arn}/*"]
    }]
  })
}

data "aws_ec2_managed_prefix_list" "s3" { name = "com.amazonaws.${var.region}.s3" }

resource "aws_security_group" "sandbox" {
  name        = "${var.name}-build-sandbox"
  description = "CodeBuild test sandbox: HTTPS to S3 only"
  vpc_id      = aws_vpc.sandbox.id
  egress {
    description     = "S3 via gateway endpoint"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.s3.id]
  }
}

# ---------------------------------------------------------------- roles
data "aws_iam_policy_document" "codebuild_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.acct]
    }
  }
}

resource "aws_iam_role" "deps" {
  name               = "${var.name}-codebuild-deps"
  assume_role_policy = data.aws_iam_policy_document.codebuild_trust.json
}

resource "aws_iam_role_policy" "deps" {
  role = aws_iam_role.deps.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = "${aws_s3_bucket.ws.arn}/runs/*" },
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${aws_s3_bucket.ws.arn}/runs/*", "${aws_s3_bucket.ws.arn}/codebuild-logs/*"] },
      { Effect = "Allow", Action = ["s3:GetBucketAcl", "s3:GetBucketLocation"], Resource = aws_s3_bucket.ws.arn },
    ]
  })
}

resource "aws_iam_role" "test" {
  name               = "${var.name}-codebuild-test"
  assume_role_policy = data.aws_iam_policy_document.codebuild_trust.json
}

resource "aws_iam_role_policy" "test" {
  role = aws_iam_role.test.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = "${aws_s3_bucket.ws.arn}/runs/*" },
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${aws_s3_bucket.ws.arn}/runs/*", "${aws_s3_bucket.ws.arn}/codebuild-logs/*"] },
      { Effect = "Allow", Action = ["s3:GetBucketAcl", "s3:GetBucketLocation"], Resource = aws_s3_bucket.ws.arn },
      # Required for CodeBuild to place the build's network interface in the sandbox subnet.
      { Effect = "Allow", Action = ["ec2:CreateNetworkInterface", "ec2:DescribeDhcpOptions", "ec2:DescribeNetworkInterfaces",
        "ec2:DeleteNetworkInterface", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups", "ec2:DescribeVpcs"],
      Resource = "*" },
      { Effect    = "Allow", Action = "ec2:CreateNetworkInterfacePermission",
        Resource  = "arn:${data.aws_partition.p.partition}:ec2:${var.region}:${local.acct}:network-interface/*",
        Condition = { StringEquals = { "ec2:Subnet" = aws_subnet.sandbox.arn, "ec2:AuthorizedService" = "codebuild.amazonaws.com" } }
      },
    ]
  })
}

# ---------------------------------------------------------------- projects
locals {
  build_image = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
}

resource "aws_codebuild_project" "deps" {
  name          = "${var.name}-deps"
  description   = "Download wheels for a generated app (binary-only, nothing executed)"
  service_role  = aws_iam_role.deps.arn
  build_timeout = 15

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.ws.bucket}/runs/placeholder/workspace.zip"
    buildspec = file("${path.module}/../buildspecs/deps.yml")
  }
  artifacts {
    type      = "S3"
    location  = aws_s3_bucket.ws.bucket
    packaging = "ZIP"
  }
  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = local.build_image
    type         = "LINUX_CONTAINER"
  }
  logs_config {
    cloudwatch_logs { status = "DISABLED" }
    s3_logs {
      status   = "ENABLED"
      location = "${aws_s3_bucket.ws.bucket}/codebuild-logs"
    }
  }
}

resource "aws_codebuild_project" "test" {
  name          = "${var.name}-test"
  description   = "Run generated code + tests with no internet access"
  service_role  = aws_iam_role.test.arn
  build_timeout = 20

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.ws.bucket}/runs/placeholder/workspace.zip"
    buildspec = file("${path.module}/../buildspecs/test.yml")
  }
  artifacts {
    type      = "S3"
    location  = aws_s3_bucket.ws.bucket
    packaging = "ZIP"
  }
  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = local.build_image
    type         = "LINUX_CONTAINER"
  }
  vpc_config {
    vpc_id             = aws_vpc.sandbox.id
    subnets            = [aws_subnet.sandbox.id]
    security_group_ids = [aws_security_group.sandbox.id]
  }
  logs_config {
    cloudwatch_logs { status = "DISABLED" }
    s3_logs {
      status   = "ENABLED"
      location = "${aws_s3_bucket.ws.bucket}/codebuild-logs"
    }
  }
  depends_on = [aws_iam_role_policy.test]
}
