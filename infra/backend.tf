# Remote state. Bucket and key are passed at init time (see scripts/migrate-state.sh)
# so no account-specific values are committed.
terraform {
  backend "s3" {}
}
