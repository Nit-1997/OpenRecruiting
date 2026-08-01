# Feedback Agent - Complete Context Document

## Overview

The **feedback_agent** is an AI-powered interview feedback processing system that integrates with the **openrecruiting-backend** FastAPI application. It processes interview transcripts to extract, validate, and judge feedback against scorecard questions.

**Deployment Target:**
- **Lambda Function**: `feedback-agent-worker` (AWS Lambda)
- **Invoked From**: openrecruiting-backend FastAPI server running on EC2 inside Docker
- **Database**: Supabase (shared with openrecruiting-backend)

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PRODUCTION FLOW                                 │
└─────────────────────────────────────────────────────────────────────────────┘

                    ┌──────────────────────┐
                    │   Recall.ai Webhook  │
                    │  (Bot Status/Events) │
                    └──────────┬───────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         EC2 Instance (Docker)                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                       openrecruiting-backend (FastAPI)                          │ │
│  │                                                                        │ │
│  │  POST /api/v1/webhooks/recall/bot-status                              │ │
│  │       │                                                                │ │
│  │       ├─► Store transcript in Supabase                                │ │
│  │       │                                                                │ │
│  │       └─► boto3.invoke(                                               │ │
│  │               FunctionName="feedback-agent-worker",                    │ │
│  │               InvocationType="Event",  # Async, fire-and-forget       │ │
│  │               Payload={"candidate_round_id": "..."}                    │ │
│  │           )                                                            │ │
│  │                                                                        │ │
│  │  Returns 202 Accepted immediately                                      │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
                               │
                               │ Async Lambda Invocation
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         AWS Lambda                                           │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                   feedback-agent-worker                                │ │
│  │                                                                        │ │
│  │  Input: { "candidate_round_id": "uuid" }                              │ │
│  │                                                                        │ │
│  │  Pipeline:                                                             │ │
│  │  1. Fetch data from Supabase (transcript, questions, role)            │ │
│  │  2. Parse & chunk interview transcript                                 │ │
│  │  3. Map chunks to scorecard topics (Claude LLM)                       │ │
│  │  4. Extract feedback from feedback transcript (Claude LLM)            │ │
│  │  5. Link feedback to evidence (Claude LLM)                            │ │
│  │  6. Judge feedback credibility (Claude LLM)                           │ │
│  │  7. Save results to Supabase                                          │ │
│  │                                                                        │ │
│  │  Output: { "statusCode": 200, "status": "completed" }                 │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Supabase                                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────────────┐ │
│  │  transcripts    │  │ candidate_rounds │  │   candidate_feedback        │ │
│  │  - segments     │  │ - rating         │  │   - feedback_text           │ │
│  │  - feedback_ts  │  │ - summary        │  │   - evidence[]              │ │
│  │                 │  │ - status         │  │   - evidence_status         │ │
│  └─────────────────┘  └─────────────────┘  └──────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Codebase Structure

### feedback_agent (`/Users/nitinbhat/PycharmProjects/feedback_agent`)

```
feedback_agent/
├── src/                          # Core business logic (shared)
│   ├── clients/
│   │   ├── anthropic.py          # Claude LLM client with retry logic
│   │   └── supabase.py           # Supabase REST API client
│   ├── chunking/
│   │   ├── semantic_chunker.py   # Main chunking orchestrator
│   │   ├── semantic_boundary.py  # Embedding-based boundary detection
│   │   ├── sentence_splitter.py  # Sentence-level splitting
│   │   └── config.py             # Chunking parameters
│   ├── config/
│   │   └── settings.py           # Pydantic settings from .env
│   ├── jobs/
│   │   ├── processor.py          # JobProcessor - main pipeline executor
│   │   └── retry.py              # Retry logic for failed jobs
│   ├── logging/
│   │   └── __init__.py           # structlog JSON/text logging
│   ├── models/
│   │   ├── pydantic_models.py    # Core data classes
│   │   ├── requests.py           # API request schemas
│   │   ├── responses.py          # API response schemas
│   │   └── chunk.py              # Utterance/Chunk models
│   ├── parsers/
│   │   ├── transcript.py         # Multi-format transcript parser
│   │   ├── json_response.py      # LLM JSON extraction
│   │   └── formats.py            # Format enum definitions
│   ├── prompts/
│   │   ├── topic_mapping.txt     # Map chunks to topics
│   │   ├── feedback_extract.txt  # Extract feedback bullets
│   │   ├── feedback_condense.txt # Condense raw feedback
│   │   ├── evidence_extraction.txt
│   │   ├── judge.txt             # Judge credibility
│   │   ├── participant_detection.txt
│   │   └── loader.py             # Prompt template loader
│   ├── services/
│   │   ├── interview.py          # InterviewPipeline
│   │   ├── feedback.py           # FeedbackPipeline
│   │   ├── evidence.py           # EvidenceService
│   │   ├── judge.py              # JudgeService
│   │   ├── orchestrator.py       # FeedbackOrchestrator (full pipeline)
│   │   └── embedding.py          # Embedding service (BGE model)
│   └── utils/
│       ├── speakers.py           # Speaker detection utilities
│       ├── tokens.py             # Token counting
│       └── time_format.py        # Timestamp formatting
│
├── local/                        # Local development
│   ├── api/
│   │   ├── app.py                # FastAPI application
│   │   └── routes/
│   │       ├── health.py         # /health endpoint
│   │       ├── topics.py         # /map-topics
│   │       ├── feedback.py       # /process-feedback
│   │       ├── complete.py       # /process-complete
│   │       ├── evidence.py       # /extract-evidence
│   │       ├── judge.py          # /judge-feedback
│   │       └── rounds.py         # /rounds (Supabase integration)
│   └── ui/
│       ├── round_tester.py       # Main Streamlit app
│       └── ...                   # UI components
│
├── production/                   # Lambda deployment
│   ├── Dockerfile                # Lambda-optimized image
│   └── handler.py                # Lambda entry point
│
├── integration/                  # Integration endpoints
│   └── feedback_job_endpoint.py  # FastAPI router for openrecruiting-backend
│
├── deploy/                       # Deployment scripts
│   ├── iam-policy.json           # IAM permissions
│   └── ecr-push.sh               # Container build → ECR → Lambda (the deploy method)
│
├── docker-compose.yml            # Local development stack
├── Dockerfile                    # Local development image
├── requirements.txt              # Python dependencies
└── .env.example                  # Environment template
```

### openrecruiting-backend (`the backend directory`)

```
openrecruiting-backend/
├── app/
│   ├── main.py                   # FastAPI entry point
│   ├── config.py                 # Settings management
│   ├── dependencies.py           # Auth, JWT validation, caching
│   ├── logging_config.py         # Logging setup
│   ├── models/
│   │   ├── user.py
│   │   ├── organization.py
│   │   ├── requisitions.py       # Job position models
│   │   └── feedback_llm.py       # Feedback processing models
│   ├── services/
│   │   ├── supabase.py           # Supabase client wrapper
│   │   ├── llm_service.py        # LiteLLM integration
│   │   ├── recall_service.py     # Recall.ai meeting bot
│   │   └── feedback_processor.py # Current (to be replaced) feedback processing
│   ├── prompts/                  # LLM prompts (legacy)
│   └── api/v1/
│       ├── router.py             # Main router
│       ├── admin/                # Staff-only endpoints
│       │   └── requisitions.py   # Requisition CRUD
│       ├── user/                 # User endpoints
│       │   └── candidates.py     # Candidate management
│       ├── public/               # Public endpoints
│       │   └── assessments.py    # Candidate assessments
│       └── webhooks/
│           └── recall.py         # Recall.ai webhooks
├── Dockerfile
└── requirements.txt
```

---

## Database Schema (Supabase)

### Tables Used by feedback_agent

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `candidate_rounds` | Interview instances | id, candidate_id, round_id, status, rating, summary, processing_status |
| `transcripts` | Interview recordings | candidate_round_id, segments (JSONB), feedback_transcript, duration_seconds |
| `feedback_questions` | Scorecard questions | round_id, question_number, heading, description |
| `candidate_feedback` | Processed feedback | candidate_round_id, feedback_question_id, feedback_text, evidence[], evidence_status |
| `recall_bots` | Bot metadata | candidate_round_id, feedback_started_at, joined_at |
| `candidates` | Candidate info | id, name, requisition_id |
| `requisitions` | Job details | role_title, must_have_skills[], job_description, intake_notes |

### Processing Status Flow

```
pending → processing → completed
                   ↘ failed (with error message)
```

---

## Processing Pipeline

### Stage 1: Interview Chunking & Topic Mapping

```
Interview Transcript (from Recall.ai)
    │
    ├─► TranscriptParser
    │   - Detects format (plain/speaker-labeled/JSON/Recall)
    │   - Extracts utterances with timestamps and speakers
    │
    ├─► SemanticChunker
    │   - Splits into sentences
    │   - Computes embeddings (BGE model)
    │   - Detects semantic boundaries
    │   - Groups into chunks (respecting speaker turns)
    │
    ├─► ParticipantDetection (LLM: Haiku)
    │   - Auto-detects candidate vs interviewer
    │
    └─► TopicMapping (LLM: Sonnet)
        - Maps each chunk to scorecard topics
        - Output: topic_id, heading, relevant_chunk_ids, reasoning
```

### Stage 2: Feedback Extraction

```
Feedback Transcript (interviewer's post-interview comments)
    │
    ├─► FeedbackExtraction (LLM: Sonnet)
    │   - Extracts raw feedback bullets
    │   - Identifies sentiment (positive/negative/neutral)
    │
    └─► FeedbackCondensation (LLM: Sonnet)
        - Condenses into structured feedback
        - Groups by topic
        - Output: feedback_bullet, antifeedback_bullet, sentiment
```

### Stage 3: Evidence Linking

```
Interview Chunks + Topic Mappings + Feedback
    │
    └─► EvidenceExtraction (LLM: Sonnet)
        - For each feedback bullet:
          - Find supporting evidence from interview
          - Find contradicting evidence
        - Output: evidence[], reasoning
```

### Stage 4: Judgment

```
Enriched Feedback + Role Context
    │
    └─► JudgeFeedback (LLM: Sonnet)
        - Compare against job requirements
        - Determine: supported/contradicted/partial/none
        - Output: evidence_status, final_reasoning
```

---

## Lambda Configuration

The Lambda is deployed as a **container image** (us-west-1, function
`feedback-agent-worker`) via `./deploy/ecr-push.sh` — memory 3008 MB, timeout 900s.
(A legacy Serverless-Framework zip config was removed 2026-06-01; ecr-push is the
sole deploy method.)

### Lambda Handler (`production/handler.py`)

```python
def handler(event, context):
    """
    Lambda entry point.

    Input:  { "candidate_round_id": "uuid" }
    Output: { "statusCode": 200, "status": "completed" }
    """
    candidate_round_id = event.get("candidate_round_id")

    if not candidate_round_id:
        return {"statusCode": 400, "error": "candidate_round_id required"}

    result = asyncio.run(process_feedback(candidate_round_id))

    return {
        "statusCode": 200,
        "candidate_round_id": candidate_round_id,
        "status": result,
    }
```

---

## Integration with openrecruiting-backend

### Option 1: Direct Lambda Invocation (Recommended)

Add this endpoint to openrecruiting-backend:

```python
# app/api/v1/jobs/feedback.py

import boto3
import json
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/jobs/feedback", tags=["Feedback Jobs"])

AWS_REGION = "us-east-1"
FEEDBACK_LAMBDA_NAME = "feedback-agent-worker"

_lambda_client = None

def get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda", region_name=AWS_REGION)
    return _lambda_client

@router.post("/{candidate_round_id}")
async def submit_feedback_job(candidate_round_id: str):
    """
    Submit feedback processing job to Lambda.
    Returns immediately - processing happens async.
    """
    try:
        lambda_client = get_lambda_client()
        lambda_client.invoke(
            FunctionName=FEEDBACK_LAMBDA_NAME,
            InvocationType="Event",  # Async invocation
            Payload=json.dumps({"candidate_round_id": candidate_round_id}),
        )
        return {"status": "accepted", "candidate_round_id": candidate_round_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Option 2: Invoke from Recall Webhook

Modify `app/api/v1/webhooks/recall.py`:

```python
import boto3
import json

async def fetch_and_store_recording(candidate_round_id: str, ...):
    # ... existing code to store transcript ...

    # Invoke Lambda instead of processing inline
    lambda_client = boto3.client("lambda", region_name="us-east-1")
    lambda_client.invoke(
        FunctionName="feedback-agent-worker",
        InvocationType="Event",
        Payload=json.dumps({"candidate_round_id": candidate_round_id}),
    )
```

---

## Environment Variables

### feedback_agent Lambda

| Variable | Description | Example |
|----------|-------------|---------|
| `ENVIRONMENT` | Deployment environment | `production` |
| `LOG_FORMAT` | Logging format | `json` |
| `ANTHROPIC_API_KEY` | Claude API key | `sk-ant-...` |
| `SUPABASE_URL` | Supabase project URL | `https://xxx.supabase.co` |
| `SUPABASE_SECRET_KEY` | Service role key | `eyJ...` |
| `EMBEDDING_CACHE_DIR` | Model cache path | `/tmp/models` |

### openrecruiting-backend EC2

| Variable | Description |
|----------|-------------|
| `AWS_REGION` | Lambda region |
| `FEEDBACK_LAMBDA_NAME` | Lambda function name |
| IAM Role | Must have `lambda:InvokeFunction` permission |

---

## Deployment Commands

### Deploy Lambda

```bash
# From feedback_agent directory
cd /Users/nitinbhat/PycharmProjects/feedback_agent

# Set environment variables
export AWS_REGION=us-east-1
export SUPABASE_URL=https://xxx.supabase.co
export SUPABASE_SECRET_KEY=eyJ...
export ANTHROPIC_API_KEY=sk-ant-...

# Build the container image, push to ECR, and update the Lambda
# (defaults to the openrecruiting-prod AWS profile):
./deploy/ecr-push.sh
```

### Local Development

```bash
# Start local stack
docker-compose up --build

# Access:
# - API: http://localhost:8001
# - UI:  http://localhost:8501
```

---

## IAM Policy for Lambda

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "LambdaBasicExecution",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    },
    {
      "Sid": "SecretsManagerAccess",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:us-east-1:*:secret:feedback-agent/*"
    }
  ]
}
```

### IAM Policy for EC2 (openrecruiting-backend)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeFeedbackLambda",
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": "arn:aws:lambda:us-east-1:*:function:feedback-agent-worker"
    }
  ]
}
```

---

## Key Files Reference

### feedback_agent

| File | Purpose |
|------|---------|
| `production/handler.py` | Lambda entry point |
| `src/jobs/processor.py` | Main pipeline executor |
| `src/services/orchestrator.py` | Pipeline orchestration |
| `src/clients/supabase.py` | Database client |
| `src/clients/anthropic.py` | LLM client |
| `deploy/ecr-push.sh` | Container build → ECR → Lambda deploy |
| `deploy/iam-policy.json` | Deploy IAM permissions |

### openrecruiting-backend

| File | Purpose |
|------|---------|
| `app/api/v1/webhooks/recall.py` | Webhook handler (trigger point) |
| `app/services/feedback_processor.py` | Legacy feedback processor (to be replaced) |
| `app/services/supabase.py` | Database client |
| `app/config.py` | Settings management |

---

## Migration Strategy

### Current State (openrecruiting-backend inline processing)
```
Recall Webhook → fetch_recording → process_interview_feedback() → Update DB
                                   (inline, blocking)
```

### Target State (Lambda)
```
Recall Webhook → fetch_recording → boto3.invoke(Lambda) → Return 202
                                           ↓
                              Lambda: process → Update DB
```

### Steps to Migrate

1. **Deploy Lambda**
   ```bash
   cd /Users/nitinbhat/PycharmProjects/feedback_agent
   ./deploy/ecr-push.sh
   ```

2. **Add IAM Role to EC2**
   - Attach policy allowing `lambda:InvokeFunction`

3. **Update openrecruiting-backend**
   - Add boto3 to requirements
   - Replace inline processing with Lambda invocation

4. **Test**
   - Schedule test interview
   - Verify transcript stored correctly
   - Verify Lambda invoked
   - Verify feedback saved to Supabase

---

## Monitoring & Debugging

### CloudWatch Logs

Lambda logs are written to `/aws/lambda/feedback-agent-worker` in JSON format:

```json
{"event": "worker_start", "candidate_round_id": "uuid", "timestamp": "..."}
{"event": "stage_complete", "stage": "topic_mapping", "chunks": 15}
{"event": "worker_complete", "candidate_round_id": "uuid", "duration_ms": 45000}
```

### Supabase Status Check

```sql
SELECT
    cr.id,
    cr.processing_status,
    cr.processing_error,
    cr.processing_started_at,
    cr.processing_completed_at,
    COUNT(cf.id) as feedback_count
FROM candidate_rounds cr
LEFT JOIN candidate_feedback cf ON cf.candidate_round_id = cr.id
WHERE cr.id = 'uuid'
GROUP BY cr.id;
```

### Retry Failed Jobs

```python
# Via openrecruiting-backend endpoint
POST /api/v1/jobs/feedback/{candidate_round_id}/retry
```

---

## LLM Models Used

| Task | Model | Reason |
|------|-------|--------|
| Participant Detection | Claude Haiku 3.5 | Fast, cheap, simple task |
| Topic Mapping | Claude Sonnet 4.5 | Nuanced understanding needed |
| Feedback Extraction | Claude Sonnet 4.5 | Complex reasoning |
| Evidence Linking | Claude Sonnet 4.5 | Multi-document analysis |
| Judgment | Claude Sonnet 4.5 | Critical decision making |

---

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Lambda Memory | 3008 MB |
| Lambda Timeout | 15 minutes |
| Typical Processing Time | 30-60 seconds |
| LLM Calls per Job | 5-15 (depending on chunks) |
| Max Concurrent Jobs | 5 (reserved concurrency) |

---

## Security Considerations

1. **API Keys**: Stored in environment variables (Lambda config or AWS Secrets Manager)
2. **Supabase**: Uses service role key (full access) - keep secure
3. **No User Data in Logs**: Avoid logging transcript content
4. **VPC**: Lambda can run in default VPC (no special config needed for Supabase)

---

## Quick Reference

### Start Local Development
```bash
cd /Users/nitinbhat/PycharmProjects/feedback_agent
docker-compose up --build
```

### Deploy to Production
```bash
./deploy/ecr-push.sh
```

### Test Lambda Locally
```bash
# Using AWS SAM
sam local invoke -e test-event.json

# Or direct Python
python -c "from production.handler import handler; print(handler({'candidate_round_id': 'test'}, None))"
```

### Check Processing Status
```bash
# Supabase SQL
SELECT processing_status, processing_error FROM candidate_rounds WHERE id = 'uuid';
```
