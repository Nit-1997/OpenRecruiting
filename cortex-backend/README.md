# OpenRecruiting Cortex Backend

The intelligence engine powering Scout's recruitment platform. Builds a temporal knowledge graph from interview data that compounds over time, enabling sourcing intelligence, interviewer coaching, pipeline health analysis, and industry benchmarking.

## Architecture

- **Graphiti + Neo4j** — Temporal knowledge graph with entity resolution and contradiction detection
- **Two ingestion modes** — `add_triplet()` for structured data ($0 LLM cost), `add_episode()` for unstructured text
- **Ontology-first** — TTL/OWL recruitment ontology constrains extraction, validation, and retrieval
- **SQS-triggered pipeline** — Decoupled ingestion from feedback agent, intake agent, and backfill scripts
- **Three-tier ontology** — Base (universal O*NET) → Organization-specific → Industry (cross-org benchmarks)
- **Intelligence layer** — Supabase PostgreSQL for signals, insights, recipes, interviewer profiles

## Documentation

- [Cortex V2 Design Spec](docs/cortex-v2-design.md) — Full architecture, ontology, ingestion pipeline, implementation timeline
- V1 Spec (superseded): `docs/superpowers/specs/2026-04-13-cortex-design.md` in OpenRecruiting root

## Infrastructure

| Component | Tech | Notes |
|---|---|---|
| Graph database | Neo4j Aura Free → Professional | 200K nodes free tier, ~18 months runway |
| Graph engine | Graphiti | Entity resolution, temporal edges, hybrid retrieval |
| Event queue | SQS + DLQ | `cortex-ingestion-events` |
| Ingestion worker | AWS Lambda (Python) | Same deploy pattern as openrecruiting-feedback-agent |
| Intelligence tables | Supabase PostgreSQL | brain_signals, brain_insights, brain_ontology, etc. |
| Embeddings | OpenAI text-embedding-3-small | Via Graphiti embedder |
| LLM (episodic extraction) | Claude Sonnet | Via Graphiti Anthropic client |

## Quick Start

See the [implementation timeline](docs/cortex-v2-design.md#implementation-timeline) in the design spec.
