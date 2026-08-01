#!/usr/bin/env bash
set -euo pipefail

# Deploy feedback-agent-worker Lambda to the OpenRecruiting prod AWS account.
#
# Usage (just run it — defaults to the openrecruiting-prod AWS profile):
#   ./deploy/ecr-push.sh
#
# Override the profile / account if needed:
#   AWS_PROFILE=other ./deploy/ecr-push.sh
#   OPENRECRUITING_AWS_ACCOUNT_ID=771834037235 ./deploy/ecr-push.sh
#
# PINS the target to the OpenRecruiting production account and refuses to run if the
# active AWS credentials resolve elsewhere — preventing accidental pushes.

# Default to the OpenRecruiting prod profile so a bare `./deploy/ecr-push.sh` works.
export AWS_PROFILE="${AWS_PROFILE:-openrecruiting-prod}"

REGION="${AWS_REGION:-us-west-1}"
OPENRECRUITING_AWS_ACCOUNT_ID="${OPENRECRUITING_AWS_ACCOUNT_ID:-771834037235}"
REPO_NAME="openrecruiting-ai/feedback-agent-worker"
FUNCTION_NAME="feedback-agent-worker"
ECR_URI="${OPENRECRUITING_AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}"

cd "$(dirname "$0")/.."

echo "==> Using AWS_PROFILE=${AWS_PROFILE}, region ${REGION}"
echo "==> Verifying AWS credentials resolve to account ${OPENRECRUITING_AWS_ACCOUNT_ID}"
ACTIVE_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
ACTIVE_ARN="$(aws sts get-caller-identity --query Arn --output text)"
if [[ "$ACTIVE_ACCOUNT" != "$OPENRECRUITING_AWS_ACCOUNT_ID" ]]; then
    echo "ERROR: active AWS credentials are for account ${ACTIVE_ACCOUNT}"
    echo "       (${ACTIVE_ARN})"
    echo "       Expected account: ${OPENRECRUITING_AWS_ACCOUNT_ID}"
    echo ""
    echo "Fix one of:"
    echo "  1. Ensure the 'openrecruiting-prod' AWS profile exists (aws configure --profile openrecruiting-prod)"
    echo "  2. Override the profile:  AWS_PROFILE=<prod-profile> ./deploy/ecr-push.sh"
    echo "  3. Override the target account (rare):  OPENRECRUITING_AWS_ACCOUNT_ID=${ACTIVE_ACCOUNT} ./deploy/ecr-push.sh"
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
    aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION" || true
    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --memory-size 3008 \
        --timeout 900 \
        --region "$REGION"
else
    echo "Function $FUNCTION_NAME does not exist — create it manually:"
    echo "  Image URI: ${ECR_URI}:latest"
    echo "  Memory: 3008 MB   Timeout: 900s"
    exit 1
fi

echo "==> Done. ARN:"
aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" \
    --query 'Configuration.FunctionArn' --output text
