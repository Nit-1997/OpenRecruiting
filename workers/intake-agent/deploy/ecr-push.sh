#!/usr/bin/env bash
set -euo pipefail

# Deploy intake-agent-v2-worker Lambda to the OpenRecruiting prod AWS account.
#
# Usage (just run it — defaults to the openrecruiting-prod AWS profile):
#   ./deploy/ecr-push.sh
#
# Override the profile / account if needed:
#   AWS_PROFILE=other ./deploy/ecr-push.sh
#   OPENRECRUITING_AWS_ACCOUNT_ID=771834037235 ./deploy/ecr-push.sh
#
# This script PINS the target AWS account to the OpenRecruiting production account.
# It will refuse to run if the active AWS CLI credentials resolve to a
# different account — preventing accidental pushes to a personal account.

# Default to the OpenRecruiting prod profile so a bare `./deploy/ecr-push.sh` works.
export AWS_PROFILE="${AWS_PROFILE:-openrecruiting-prod}"

REGION="${AWS_REGION:-us-west-1}"
OPENRECRUITING_AWS_ACCOUNT_ID="${OPENRECRUITING_AWS_ACCOUNT_ID:-771834037235}"
REPO_NAME="openrecruiting-ai/intake-agent-v2-worker"
FUNCTION_NAME="intake-agent-v2-worker"
ECR_URI="${OPENRECRUITING_AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}"

cd "$(dirname "$0")/.."

echo "==> Verifying AWS credentials resolve to account ${OPENRECRUITING_AWS_ACCOUNT_ID}"
ACTIVE_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
ACTIVE_ARN="$(aws sts get-caller-identity --query Arn --output text)"
if [[ "$ACTIVE_ACCOUNT" != "$OPENRECRUITING_AWS_ACCOUNT_ID" ]]; then
    echo "ERROR: active AWS credentials are for account ${ACTIVE_ACCOUNT}"
    echo "       (${ACTIVE_ARN})"
    echo "       Expected account: ${OPENRECRUITING_AWS_ACCOUNT_ID}"
    echo ""
    echo "Fix one of:"
    echo "  1. Set AWS_PROFILE to a profile in the OpenRecruiting prod account:"
    echo "       AWS_PROFILE=openrecruiting-prod ./deploy/ecr-push.sh"
    echo "  2. Reconfigure your default profile with prod credentials"
    echo "  3. Override the target account (rare):"
    echo "       OPENRECRUITING_AWS_ACCOUNT_ID=${ACTIVE_ACCOUNT} ./deploy/ecr-push.sh"
    exit 1
fi
echo "    OK: ${ACTIVE_ARN}"

echo "==> Logging in to ECR (${ECR_URI})"
aws ecr get-login-password --region "$REGION" | \
    docker login --username AWS --password-stdin "${OPENRECRUITING_AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "==> Ensuring ECR repo exists"
aws ecr describe-repositories --repository-names "$REPO_NAME" --region "$REGION" >/dev/null 2>&1 || \
    aws ecr create-repository --repository-name "$REPO_NAME" --region "$REGION"

echo "==> Building image (platform linux/amd64)"
docker build --platform linux/amd64 -t "${REPO_NAME}:latest" -f production/Dockerfile .

echo "==> Tagging + pushing"
docker tag "${REPO_NAME}:latest" "${ECR_URI}:latest"
docker push "${ECR_URI}:latest"

echo "==> Updating Lambda function (or warning if missing)"
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --image-uri "${ECR_URI}:latest" \
        --region "$REGION"
    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --memory-size 1024 \
        --timeout 300 \
        --region "$REGION"
else
    echo "Function $FUNCTION_NAME does not exist — create manually via AWS console:"
    echo "  Image URI: ${ECR_URI}:latest"
    echo "  Memory: 1024 MB"
    echo "  Timeout: 300s"
    echo "  Env vars: LLM_GATEWAY_URL, LITELLM_MASTER_KEY, SUPABASE_URL, SUPABASE_SECRET_KEY,"
    echo "            SQS_QUEUE_URL, SQS_REGION, LOG_LEVEL, LOG_FORMAT"
    echo "  (AWS_REGION is reserved by Lambda — set automatically, do not configure)"
    exit 1
fi

echo "==> Done. ARN:"
aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" \
    --query 'Configuration.FunctionArn' --output text
