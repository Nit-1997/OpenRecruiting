# Scout Voice Agent

AI-powered voice agent for two modes:
1. **Post-interview feedback collection** — runs inside a Recall.ai bot, talks to interviewers after calls end
2. **Pre-interview intake calls** — runs in the recruiter UI, helps recruiters define interview plans via voice

## Architecture

```
                    Recall Bot (headless Chromium)
                    ┌────────────────────────────┐
                    │  Frontend (Next.js 3003)   │
                    │  SmallWebRTCTransport       │
                    └──────────┬─────────────────┘
                               │ WebRTC (Opus 48kHz)
                               │ SDP signaling via HTTP POST
                               ▼
                    ┌────────────────────────────┐
                    │  Pipecat Server (8001)      │
                    │  FastAPI + SmallWebRTC      │
                    │                            │
                    │  POST /api/offer/{token}   │
                    │  PATCH /api/offer           │
                    └──┬─────────┬──────────┬────┘
                       │         │          │
                       ▼         ▼          ▼
                   Deepgram   Anthropic   Deepgram
                   Flux STT   Claude      TTS
                   (16kHz)    (Sonnet)    (24kHz)
                               │
                               ▼
                          Supabase
                     (transcripts, status)
```

For intake calls, the recruiter's browser connects directly (no Recall bot).

## Pipeline Architecture

The Pipecat pipeline is a chain of 14 frame processors. Frames flow left-to-right for normal processing and right-to-left for interruptions.

```
transport.input()
  → DeepgramFluxSTT          [Speech-to-text with end-of-turn detection]
  → PostEndInputGate         [Blocks user input after [END] marker]
  → UserAggregator           [Accumulates user speech into context]
  → FillerProcessor          [Injects "Hmm..." after 2s silence]
  → AnthropicLLM             [Claude with cached system prompt]
  → MarkdownStripper         [Removes **bold**, *italic* etc. for TTS]
  → EndOfConversationDetector [Detects [END] marker + goodbye patterns]
  → DeepgramTTS              [Text-to-speech, sentence-level streaming]
  → TTSNameNormalizer        [Fixes pronunciation: "Mayzle" → "Maze-ul"]
  → transport.output()
  → InterruptContextCleaner  [Annotates truncated messages on barge-in]
  → AssistantAggregator      [Accumulates assistant speech into context]
  → MetricsLogger            [Per-turn RTL breakdown: STT/LLM/TTS ms]
```

### Why Pipecat

Pipecat provides a frame-based processing system with two priority queues:
- **SystemFrame** (high priority): InterruptionFrame, EndFrame — these bypass the processing queue and propagate immediately
- **DataFrame** (normal priority): audio, text, LLM responses — these queue normally

This architecture gives us:
- **Atomic interruption handling**: when the user barges in, InterruptionFrame propagates instantly through all processors, draining queued audio
- **Sentence-level TTS streaming**: LLM output is split at sentence boundaries and streamed to TTS concurrently, reducing perceived latency
- **Context summarization**: when conversation grows beyond 8000 tokens, older messages are summarized to fit target of 6000
- **EagerEndOfTurn support**: Deepgram Flux signals when the user is likely done speaking (before silence timeout), enabling faster responses

Hand-rolled pipelines consistently fail at interruption handling — they either don't drain the TTS queue (causing audio overlap) or they lose context on interrupted messages.

## Deepgram Flux Integration

Deepgram Flux provides real-time speech-to-text with TurnInfo events that indicate end-of-turn probability.

Configuration:
- `eot_threshold: 0.7` — standard end-of-turn confidence
- `eager_eot_threshold: 0.4` — "eager" mode triggers early with lower confidence
- `eot_timeout_ms: 3000` — hard timeout after 3s of silence
- `min_confidence: 0.3` — filter out low-confidence transcriptions (reduces false LLM triggers)

Flux events map to Pipecat's `ExternalUserTurnStrategies`, which means Pipecat delegates turn detection entirely to Deepgram rather than using VAD.

## SmallWebRTC Transport

The voice agent uses Pipecat's SmallWebRTC transport instead of WebSocket for browser-native audio:

**Why WebRTC over WebSocket:**
- Browser-native Acoustic Echo Cancellation (AEC) — prevents bot audio from feeding back into the mic
- ICE for NAT traversal — works behind firewalls without special configuration
- Opus codec at 48kHz — better audio quality than raw PCM over WebSocket
- No RMS-based barge-in hack needed — AEC handles echo cancellation natively

**SDP signaling flow:**
1. Client creates RTCPeerConnection with ICE servers
2. Client POSTs SDP offer to `/api/offer/{token}`
3. Server validates token, creates SmallWebRTCConnection, returns SDP answer
4. Client sends ICE candidates via PATCH `/api/offer`
5. WebRTC peer connection established, audio flows bidirectionally
6. Pipeline runs as a background task on the server

## Session Lifecycle

### Feedback sessions (post-interview)
```
dormant → activating → active → completed
           │                      │
           │ Frontend polls       │ Transcript stored,
           │ /voice/status/{t}    │ bot leaves meeting
           │                      │
           └──────────────────────┘
```
- Timeout: 600s (wrap-up warning at 570s)
- On completion: transcript stored in `transcripts.feedback_transcript`
- Bot leaves Recall meeting after session ends

### Intake sessions (pre-interview)
```
pending → active → completed
                     │
                     │ Transcript stored in
                     │ requisitions.intake_transcript
                     └─────────────────────────────
```
- Timeout: 900s (wrap-up warning at 870s)
- Instant disconnects (<5s, empty transcript) reset status to `pending` for retry

## Context Management

LLM context is managed with summarization to prevent token overflow:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `max_context_tokens` | 8000 | Trigger summarization above this |
| `target_context_tokens` | 6000 | Summarize down to this size |
| `max_unsummarized_messages` | 20 | Force summarization after N messages |
| `min_messages_after_summary` | 4 | Keep at least N recent messages unsummarized |

The system prompt uses Anthropic prompt caching (`cache_control: ephemeral`) so the ~2400-token persona prompt is cached across turns.

## Configuration

All config via environment variables (loaded from `deploy-config/.env-fastapi`):

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SECRET_KEY` | Supabase service role key |
| `RECALL_API_KEY` | Recall.ai API key (for leaving meetings) |
| `RECALL_BASE_URL` | Recall API base URL |
| `VOICE_DEEPGRAM_API_KEY` | Deepgram API key |
| `LLM_GATEWAY_URL` | LiteLLM gateway base URL (default: `http://litellm:4000`) |
| `LITELLM_MASTER_KEY` | Authenticates this service to the gateway. **This service holds no provider API key** — the gateway does. |
| `VOICE_INTAKE_MODEL` | Gateway alias for both intake pipelines (default: `voice-intake`) |
| `VOICE_SCREENING_MODEL` | Gateway alias for the screening pipeline (default: `voice-screening`) |
| `VOICE_FEEDBACK_MODEL` | Gateway alias for both feedback pipelines (default: `voice-feedback`) |
| `VOICE_TTS_VOICE` | Deepgram TTS voice (default: aura-2-helena-en) |
| `ICE_STUN_SERVERS` | STUN server URLs (JSON list) |
| `TURN_SERVER_URL` | Optional TURN server URL |
| `TURN_USERNAME` | TURN server username |
| `TURN_CREDENTIAL` | TURN server credential |

## Development

### Local setup
```bash
cd voice-agent
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend
```bash
cd voice-agent/frontend
npm install
npm run dev  # port 3003
```

### Docker build
```bash
cd voice-agent
docker build -t voice-agent .
```

### Production deployment
```bash
cd deploy-config/backend-deploy
docker-compose up -d --build voice-agent voice-agent-frontend
```

Caddy routes `localhost:8004/voice-ws/*` to the voice agent (port 8001). The `handle_path` directive strips the `/voice-ws` prefix before proxying.

## File Structure

```
voice-agent/
├── src/
│   ├── main.py                    # FastAPI server, WebRTC signaling, session management
│   ├── config.py                  # Pydantic settings
│   ├── persona/
│   │   ├── generator.py           # Feedback persona prompt generation
│   │   └── intake_generator.py    # Intake persona prompt generation
│   └── pipeline/
│       ├── factory.py             # Pipeline assembly (14-element chain)
│       ├── services.py            # DeepgramFluxSTT, AnthropicLLM, DeepgramTTS creation
│       ├── filler.py              # Filler phrase injection (2s delay, 3s cooldown)
│       ├── end_detector.py        # [END] marker + goodbye pattern detection
│       ├── markdown_stripper.py   # Strip markdown for TTS + name pronunciation
│       ├── input_gate.py          # Block input after conversation end
│       ├── interrupt_context_cleaner.py  # Annotate truncated messages
│       └── metrics_logger.py      # Per-turn latency breakdown
├── frontend/                      # Next.js frontend loaded by Recall bot
│   └── src/
│       ├── components/voice/      # VoiceProvider, VoiceSession, VoiceOrb, DormantView
│       └── lib/pipecat.ts         # Offer URL builder + ICE server config
├── Dockerfile
└── requirements.txt
```
