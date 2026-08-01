# intake-core

Modality-agnostic intake agent state, prompts, tools, and coverage tracker.
Imported by:
- `voice-agent` (Pipecat process)
- `backend-v2` (FastAPI text agent loop)
- `workers/intake-context-builder` (prefill Lambda)
- `intake-agent` (scorecard Lambda)

## Install (dev, monorepo)

```bash
pip install -e ../intake-core
```

See spec: `docs/superpowers/specs/2026-05-27-v2-intake-agent-design.md`
