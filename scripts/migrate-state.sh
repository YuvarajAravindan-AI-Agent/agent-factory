#!/usr/bin/env bash
# One-time: move Terraform state from the laptop to S3. Run on the laptop, where
# infra/terraform.tfstate lives, with AWS credentials for account 632393508307.
set -euo pipefail
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="af-tfstate-${ACCOUNT}"

cd "$(dirname "$0")/../infra"
cp terraform.tfstate "terraform.tfstate.bak-$(date +%s)"   # local safety copy (gitignored)

if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
  aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

terraform init -migrate-state -force-copy \
  -backend-config="bucket=${BUCKET}" \
  -backend-config="key=agent-factory/terraform.tfstate" \
  -backend-config="region=${REGION}" \
  -backend-config="use_lockfile=true"
terraform plan -detailed-exitcode || [ $? -eq 2 ]   # expect "no changes" (0) or review the diff
echo "State is now in s3://${BUCKET}/agent-factory/terraform.tfstate"
