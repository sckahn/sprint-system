#!/usr/bin/env bash
# audit-shift.sh — shift today's audit events to S3 Object Lock (WORM)
# Requires: AWS_AUDIT_BUCKET, AWS_AUDIT_ROLE_ARN env vars (or GitHub Secrets)
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel 2>/dev/null || echo ".")"
AUDIT_FILE="$ROOT/.audit/events.jsonl"
DATE=$(date -u +%Y/%m/%d)
BUCKET="${AWS_AUDIT_BUCKET:-}"
ROLE_ARN="${AWS_AUDIT_ROLE_ARN:-}"

if [[ -z "$BUCKET" ]]; then
  echo "[audit-shift] SKIP: AWS_AUDIT_BUCKET not set" >&2; exit 0
fi

if [[ ! -f "$AUDIT_FILE" ]] || [[ ! -s "$AUDIT_FILE" ]]; then
  echo "[audit-shift] SKIP: no audit events to shift" >&2; exit 0
fi

# Verify chain before shipping
bash "$(dirname "$0")/audit-verify.sh" --quiet || {
  echo "[audit-shift] ERROR: chain verification failed, aborting shift" >&2; exit 1
}

S3_KEY="audit-logs/${DATE}/events-$(date -u +%Y%m%d%H%M%S).jsonl"
echo "[audit-shift] Uploading to s3://${BUCKET}/${S3_KEY}" >&2

if [[ -n "$ROLE_ARN" ]]; then
  creds=$(aws sts assume-role --role-arn "$ROLE_ARN" --role-session-name audit-shift --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text)
  export AWS_ACCESS_KEY_ID=$(echo "$creds" | awk '{print $1}')
  export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | awk '{print $2}')
  export AWS_SESSION_TOKEN=$(echo "$creds" | awk '{print $3}')
fi

aws s3 cp "$AUDIT_FILE" "s3://${BUCKET}/${S3_KEY}" \
  --no-progress \
  --metadata "sha256=$(sha256sum "$AUDIT_FILE" | awk '{print $1}')"

echo "[audit-shift] Done: s3://${BUCKET}/${S3_KEY}" >&2
