# Feedback Agent Integration Guide

## Overview

This guide explains how to integrate the feedback_agent Lambda with your existing openrecruiting-backend.

## Prerequisites

1. AWS account with ECR and Lambda access
2. openrecruiting-backend running on EC2
3. Supabase database with required tables

## Step 1: Deploy Lambda

```bash
# Build and push Docker image to ECR
cd feedback_agent
./deploy/ecr-push.sh

# Create Lambda function (first time only)
aws lambda create-function \
  --function-name feedback-agent-worker \
  --package-type Image \
  --code ImageUri=ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/feedback-agent-worker:latest \
  --role arn:aws:iam::ACCOUNT:role/feedback-agent-lambda-role \
  --timeout 900 \
  --memory-size 3008
```

## Step 2: Configure IAM

Add to your EC2 instance role:
```json
{
  "Effect": "Allow",
  "Action": "lambda:InvokeFunction",
  "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:feedback-agent-worker"
}
```

## Step 3: Add Endpoint to openrecruiting-backend

1. Copy `integration/feedback_job_endpoint.py` to `openrecruiting-backend/app/api/v1/admin/feedback_jobs.py`

2. Add to `openrecruiting-backend/app/config.py`:
```python
AWS_REGION: str = "us-east-1"
FEEDBACK_LAMBDA_NAME: str = "feedback-agent-worker"
```

3. Include router in `openrecruiting-backend/app/api/v1/admin/__init__.py`:
```python
from . import feedback_jobs
admin_router.include_router(feedback_jobs.router)
```

## Step 4: Test

```bash
# Submit a job
curl -X POST "http://localhost:8004/api/v1/admin/feedback-jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"candidate_round_id": "uuid-here"}'

# Check status
curl "http://localhost:8004/api/v1/admin/feedback-jobs/uuid-here/status" \
  -H "Authorization: Bearer $TOKEN"
```

## Environment Variables

The Lambda requires:
- `ANTHROPIC_API_KEY` - Anthropic API key
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_SECRET_KEY` - Supabase service role key

Set these in Lambda configuration or use AWS Secrets Manager.

## Monitoring

View logs in CloudWatch:
```bash
aws logs tail /aws/lambda/feedback-agent-worker --follow
```
