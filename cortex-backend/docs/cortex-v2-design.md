# OpenRecruiting Cortex — Revised Intelligence Platform Design (V2)

**Date:** 2026-05-03
**Status:** Design approved, pending implementation
**Authors:** Nitin + Claude
**Supersedes:** `docs/superpowers/specs/2026-04-13-cortex-design.md` (V1)

> **Transport note (2026-08-06):** every "SQS" in the sections below is a record of
> the design as approved, not of what runs. Producer and consumer both live in the
> cortex-backend container, so the queue between them was carrying rows out of
> Postgres and back into the same process. `cortex_events` is now the queue itself:
> `BrainSyncCron` leases a batch via `cortex_events_claim_batch()` and ingests it
> inline. Read the SQS passages as "the ingestion pipeline"; nothing else about the
> ontology, handlers, or graph model changed.

---

## Executive Summary

OpenRecruiting Cortex is the intelligence engine that absorbs recruitment data from every touchpoint, compounds it through a temporal knowledge graph, and makes it queryable to power sourcing strategies, screening decisions, interviewer coaching, and organizational hiring intelligence.

**What changed from V1:**

| Area | V1 Design | V2 Design | Why |
|------|-----------|-----------|-----|
| Ingestion model | Feed raw text to Graphiti, extract entities | Two paths: `add_triplet()` for structured data ($0), `add_episode()` for unstructured | Our feedback/intake agents already produce structured data — re-extracting wastes LLM calls |
| Ontology approach | JSON schema passed in `source_description` | Formal TTL/OWL ontology → `entity_types` + `edge_type_map` constraints | GoingMeta best practice: ontology is the hard constraint envelope, not a soft hint |
| Ingestion trigger | Inline in Cortex Agent | SQS events with mode parameter | Decoupled, supports backfill, multiple data sources, retry |
| Backfill | Not addressed | First-class pipeline for existing production data | Graph is useful from day 1 only if populated with historical data |
| Ontology storage | Supabase `brain_ontology` table only | TTL/OWL file (source of truth) + Supabase table (runtime) + Graphiti entity_types (extraction constraint) | Single ontology definition powers all three layers |

**What's unchanged from V1:**
- Three-layer architecture (Graph Engine → Intelligence → Products)
- Intelligence layer tables in Supabase (brain_signals, brain_insights, etc.)
- Insight Recipe Registry
- Cortex Agent OODA loop
- Multi-tenancy via org_id
- Cost trajectory and trigger system
- Compliance approach (EU AI Act, NYC LL144, thought trails)

---

## Architecture: One Graph, Two Ingestion Modes

```
                    ┌──────────────────────────────────────┐
                    │        RECRUITMENT ONTOLOGY            │
                    │  (TTL/OWL source of truth)             │
                    │  Three tiers: base / org / industry    │
                    │                                        │
                    │  → Generates Pydantic models           │
                    │  → Generates entity_types dict         │
                    │  → Generates edge_type_map             │
                    │  → Syncs to brain_ontology table       │
                    └──────────────┬───────────────────────┘
                                   │ constrains
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SQS INGESTION PIPELINE                        │
│                                                                  │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────────┐  │
│  │ Feedback     │    │ Data Eng     │    │ Future Sources     │  │
│  │ Agent        │    │ Backfill     │    │ (transcripts,      │  │
│  │ Completion   │    │ Script       │    │  debriefs, Slack)  │  │
│  └──────┬──────┘    └──────┬───────┘    └────────┬───────────┘  │
│         │                  │                     │               │
│         ▼                  ▼                     ▼               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              SQS: cortex-ingestion-events                 │   │
│  │  { event_type, ingestion_mode: "triplet"|"episodic",     │   │
│  │    org_id, source_ref, payload }                          │   │
│  └──────────────────────────┬───────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │        CORTEX SERVICE (FastAPI + SQS Consumer + Cron)     │   │
│  │        Docker container in backend-deploy compose          │   │
│  │                                                            │   │
│  │  if mode == "triplet":                                     │   │
│  │    → Build EntityNode + EntityEdge from structured payload │   │
│  │    → Validate against Pydantic models (from ontology)      │   │
│  │    → graphiti.add_triplet()  [no LLM, $0]                 │   │
│  │    → Entity resolution + dedup against existing graph      │   │
│  │                                                            │   │
│  │  if mode == "episodic":                                    │   │
│  │    → Pass text to graphiti.add_episode()                   │   │
│  │    → Constrained by entity_types + edge_type_map           │   │
│  │    → LLM extraction + resolution  [~$0.02-0.05]           │   │
│  │                                                            │   │
│  │  Then (both modes):                                        │   │
│  │    → Write brain_signals to Supabase                       │   │
│  │    → Match insight recipes                                 │   │
│  │    → Update brain_state                                    │   │
│  │    → Log to brain_event_log                                │   │
│  │                                                            │   │
│  │  Nightly cron:                                             │   │
│  │    → Tier promotion checks                                 │   │
│  │    → Benchmark aggregation (opted-in orgs)                 │   │
│  │    → Ontology sync (TTL → Supabase)                        │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 1: GRAPHITI + NEO4J AURA                      │
│                                                                  │
│  Entity resolution (embedding + LSH fuzzy + LLM verify)          │
│  Contradiction detection (temporal invalidation)                 │
│  Bi-temporal edges (valid_at, invalid_at, created_at)            │
│  Community detection (label propagation)                         │
│  Hybrid retrieval (BM25 + vector + graph BFS + RRF)              │
│                                                                  │
│  Multi-tenancy: group_id = org_id                                │
│  Storage: Neo4j Aura Free → Professional at scale                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 2: INTELLIGENCE (Supabase PostgreSQL)          │
│                                                                  │
│  brain_signals          brain_insights          brain_ontology   │
│  brain_interviewer_profiles    brain_human_corrections            │
│  brain_notifications    brain_state             brain_event_log  │
│  brain_insight_evaluations     brain_global.*                    │
│                                                                  │
│  Cortex Agent (OODA loop)    Insight Recipe Registry             │
│  Emergent Pattern Detector   Proactive Notification Router       │
│  Self-Evaluation Loop        Human Correction Loop               │
│                                                                  │
│  → Unchanged from V1. See original spec for full table schemas.  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 3: PRODUCTS + SURFACES                        │
│                                                                  │
│  "Ask Cortex" (Slack/Brain UI)    │  REST API (/cortex/*)       │
│  Sourcing Intelligence            │  Dashboard Views             │
│  Screening Strategy               │  Industry Benchmarks         │
│  Interviewer Coaching             │  Debrief Intelligence        │
└─────────────────────────────────────────────────────────────────┘
```

---

## The Recruitment Ontology

### Design Philosophy

The ontology is the **constraint envelope** for everything the Cortex can know. Every entity type, relationship type, and attribute must be defined in the ontology before it can appear in the graph.

This follows the GoingMeta principle (Neo4j community best practice):
> "You will never use terms not defined in the ontology. Respect the domain and range constraints."

The ontology serves three roles simultaneously:
1. **Extraction constraint** — Graphiti's `entity_types` + `edge_type_map` prevent the LLM from inventing terms
2. **Validation schema** — Pydantic models (generated from ontology) validate triplets before ingestion
3. **Query constraint** — Text2Cypher uses the ontology to generate valid Cypher (can only reference defined types)

### Three-Tier Model

```
┌─────────────────────────────────────────────────┐
│  TIER 3: INDUSTRY                                │
│  Aggregated from opt-in orgs. Cross-org terms.   │
│  Example: "DevOps Engineer" role pattern with     │
│  industry-standard competency weights             │
│  Grows via: anonymized signal aggregation         │
│  Access: orgs enrolled in benchmarking network    │
├─────────────────────────────────────────────────┤
│  TIER 2: ORGANIZATION-SPECIFIC                   │
│  Per-org terms, role patterns, competencies.      │
│  Example: "Product Sense" (Org X's specific       │
│  interpretation of product intuition)             │
│  Grows via: usage, human corrections, LLM         │
│  Access: org_id scoped                            │
├─────────────────────────────────────────────────┤
│  TIER 1: BASE (UNIVERSAL)                        │
│  ~800 terms from O*NET + standard recruiting      │
│  vocabulary. Skills, competencies, role patterns.  │
│  Immutable by orgs. Curated by Scout.             │
│  Access: all orgs, from day 1                     │
└─────────────────────────────────────────────────┘
```

**Tier promotion flow:**
```
Org X adds "product sense" (Tier 2, org-specific)
Org Y adds "product intuition" (Tier 2, org-specific)
Org Z adds "product thinking" (Tier 2, org-specific)
  → Entity resolution links all three as aliases
  → When 5+ orgs use equivalent terms → promote to Tier 3 (industry)
  → Each org keeps their local name, but it maps to the shared industry term
  → Industry benchmarks can now aggregate across the shared term
```

### Entity Types

These map directly to Graphiti's `entity_types` dict. Each Pydantic model's docstring becomes the type description in the LLM extraction prompt.

```python
from pydantic import BaseModel
from typing import Optional, Literal

class SkillEntity(BaseModel):
    """A technical, behavioral, or domain skill that candidates possess
    or roles require. Examples: 'system design', 'Python', 'leadership',
    'distributed systems'. NOT a personality trait or judgment term."""
    category: Optional[Literal["technical", "behavioral", "domain", "leadership"]] = None
    tier: Literal["base", "org", "industry"] = "base"

class RequisitionEntity(BaseModel):
    """A job opening being recruited for. Has a title, required skills,
    an interview plan with rounds, and structured experience/location requirements."""
    role_title: str
    status: Optional[Literal["intake_pending", "planned", "active", "closed"]] = None
    experience_min_years: Optional[int] = None
    experience_max_years: Optional[int] = None
    location: Optional[str] = None

class RoundEntity(BaseModel):
    """An interview round within a requisition's plan. Has a name,
    category, and assesses specific competencies.
    Production categories include: coding, design, behavioral/behavioural,
    domain, culture, assessment, presentation, screen, generic."""
    name: str
    category: Optional[Literal[
        "coding", "design", "behavioral", "domain", "culture",
        "assessment", "presentation", "screen", "generic"
    ]] = None
    duration_minutes: Optional[int] = None
    round_type: Optional[Literal["interview", "assessment"]] = None

class CompetencyEntity(BaseModel):
    """A specific evaluation dimension within an interview round.
    Examples: 'Problem Decomposition', 'Code Quality', 'System Thinking'.
    NOT a skill — a competency is what you evaluate, a skill is what you possess."""
    heading: str

class CandidateEntity(BaseModel):
    """A candidate being evaluated. Two-layer identity model:
    - ORG LEVEL: name is stored and visible within the org's group_id scope.
      Recruiters need names for re-engagement, comparison, and actionability.
    - CROSS-ORG (Tier 3 benchmarks): name is stripped during aggregation.
      Only candidate_ref (hashed ID) survives. No PII crosses org boundaries.
    Experience years inferred from requisition context and transcript/JD extraction."""
    name: str
    candidate_ref: str
    status: Optional[Literal["active", "hired", "rejected", "withdrawn"]] = None
    experience_years: Optional[int] = None

class InterviewerEntity(BaseModel):
    """A person who conducts interviews. Referenced by anonymized ID.
    Interviewer behavior and calibration are tracked over time.
    Resolution key: candidate_rounds.interviewer_email (hashed for graph storage)."""
    interviewer_ref: str

class CompanyEntity(BaseModel):
    """An organization referenced in interviews (candidate's past employers,
    target companies for sourcing, competitors). NOT the hiring organization.
    EPISODIC-ONLY: No structured production fields carry company data.
    Discovered from transcripts and intake research docs.
    Validated against production data (2026-05-05): Calendly, Vahan, Sarti,
    Philips, Gupshup, Acme all found in real transcripts."""
    name: str
    size_signal: Optional[Literal["startup", "scaleup", "enterprise", "unknown"]] = None
    domain_summary: Optional[str] = None  # LLM-generated, e.g. "scheduling/productivity SaaS"

class RolePatternEntity(BaseModel):
    """An emergent archetype across similar requisitions. Discovered by
    community detection — e.g., 'Senior Backend Engineer' pattern that
    appears across multiple requisitions with shared skill requirements."""
    pattern_name: str
    typical_round_count: Optional[int] = None

class TeamEntity(BaseModel):
    """A team or organizational unit within the hiring company.
    Captures team context relevant to hiring decisions.
    EPISODIC-ONLY: Discovered from intake transcripts and debrief meetings."""
    name: str
    size: Optional[int] = None

class LocationEntity(BaseModel):
    """A geographic location associated with a requisition or candidate.
    TRIPLET SOURCE: `requisitions.role_location` (e.g., 'Remote', 'Bangalore', 'New York').
    EPISODIC SOURCE: Candidate location mentioned in transcripts/JDs (e.g., 'India-focused')."""
    name: str
    location_type: Optional[Literal["city", "region", "country", "remote"]] = None

class TraitEntity(BaseModel):
    """A behavioral pattern, work style, or cultural attribute observed in
    candidates, interviewers, or organizations. NOT a Skill (what you know)
    or Competency (what we formally evaluate) — a Trait is the 'how' dimension.
    EPISODIC-ONLY: Extracted from transcripts, summaries, intake calls.
    Candidate examples: 'systematic executor', 'verbose communicator',
    'strong learning orientation', 'user-centered thinker'.
    Interviewer examples: 'structured assessor', 'founder-mentality tester',
    'uncertain decision-maker', 'defers to committee'.
    Cultural examples: 'collegial sparring culture', 'PLG DNA', 'high ownership'."""
    name: str
    category: Optional[Literal[
        "communication", "leadership", "execution",
        "strategic", "interpersonal", "cultural"
    ]] = None
    polarity: Optional[Literal["positive", "negative", "neutral", "contextual"]] = None

class MarketEntity(BaseModel):
    """An industry vertical, domain, customer segment, or business model.
    NOT a skill or competency. Markets represent the business context
    in which candidates have operated and companies compete.
    EPISODIC-ONLY: Extracted from transcripts, intake calls, JDs.
    Validated against production data (2026-05-05): 'B2B SaaS', 'BFSI debt
    collection', 'blue-collar recruitment', 'voice AI', 'enterprise scheduling',
    'PLG', 'developer platforms', 'healthcare/medical devices' all found."""
    name: str
    category: Optional[Literal[
        "industry", "domain", "segment", "business_model"
    ]] = None
```

### Relationship Types (Edge Type Map)

```python
EDGE_TYPE_MAP = {
    # ── Requisition structure ──
    ("Requisition", "Skill"): ["REQUIRES", "NICE_TO_HAVE"],
    ("Requisition", "Round"): ["HAS_ROUND"],
    ("Requisition", "Team"): ["FOR_TEAM"],
    ("Requisition", "RolePattern"): ["INSTANCE_OF"],
    ("Requisition", "Location"): ["LOCATED_IN"],  # triplet: requisitions.role_location
    ("Requisition", "Market"): ["TARGETS"],  # episodic: domain focus from intake/JD
    ("Requisition", "Trait"): ["VALUES"],  # episodic: HM implicit preferences from intake

    # ── Round structure ──
    ("Round", "Competency"): ["ASSESSES"],
    ("Round", "Skill"): ["ASSESSES"],

    # ── Candidate journey ──
    ("Candidate", "Requisition"): ["APPLIED_TO", "HIRED_BY", "REJECTED_BY", "WITHDREW_FROM"],
    ("Candidate", "Skill"): ["DEMONSTRATED", "CLAIMED", "LACKS"],  # episodic-only (structured → Competency)
    ("Candidate", "Competency"): ["STRONG_IN", "WEAK_IN", "ASSESSED_ON"],  # PRIMARY from structured feedback
    ("Candidate", "Company"): ["WORKED_AT"],  # episodic: career history from interviews
    ("Candidate", "Round"): ["INTERVIEWED_IN"],
    ("Candidate", "Location"): ["BASED_IN"],  # episodic: mentioned in transcripts/JDs
    ("Candidate", "Trait"): ["EXHIBITS"],  # episodic: behavioral patterns from transcripts/summaries
    ("Candidate", "Market"): ["EXPERIENCED_IN"],  # episodic: domain expertise from interviews

    # ── Interviewer ──
    ("Interviewer", "Round"): ["CONDUCTED", "DEFAULT_FOR"],
    ("Interviewer", "Candidate"): ["EVALUATED"],
    ("Interviewer", "Competency"): ["ASSESSED"],
    ("Interviewer", "Trait"): ["DEMONSTRATES"],  # episodic: assessment patterns from transcripts

    # ── Company intelligence ──
    ("Company", "Skill"): ["KNOWN_FOR"],
    ("Company", "Market"): ["OPERATES_IN"],  # episodic: industry/domain from transcripts
    ("Company", "Location"): ["BASED_IN"],  # episodic: HQ/office locations
    ("Company", "Trait"): ["HAS_CULTURE"],  # episodic: org culture from intake/JD

    # ── Derived / emergent ──
    ("Skill", "Skill"): ["RELATED_TO", "PREREQUISITE_FOR", "OFTEN_PAIRED_WITH"],
    ("Skill", "RolePattern"): ["PREDICTS_SUCCESS", "COMMONLY_REQUIRED"],
    ("Interviewer", "RolePattern"): ["CALIBRATED_FOR"],
    ("RolePattern", "RolePattern"): ["SIMILAR_TO"],

    # Catch-all for episodic discovery
    ("Entity", "Entity"): ["RELATES_TO"],
}
```

### Ontology Lifecycle

```
New term encountered during extraction:
  │
  ├─ Exact match in ontology? ──── YES → Use canonical term, increment usage_count
  │
  ├─ Alias match? ──── YES → Use canonical term, add alias if new
  │
  ├─ Embedding similarity > 0.90? ──── YES → Use canonical term, add alias
  │
  ├─ Embedding similarity 0.75-0.90? ──── MAYBE
  │     → Use provisionally, flag status='pending_review'
  │     → Notify org admin for validation
  │
  └─ No match < 0.75? ──── NEW
        → LLM classifies: is this a skill, competency, or judgment term?
        → If judgment term ("culture fit", "gut feeling") → reject, do not add
        → If valid → add as Tier 2 (org-specific), status='pending_review'
        → After human confirmation → status='active'
        → After 5+ orgs use equivalent → candidate for Tier 3 promotion
```

### Ontology Source Format (TTL/OWL)

The canonical ontology is defined in Turtle format, following GoingMeta conventions:

```turtle
@prefix orec: <https://openrecruiting.example/ontology/recruitment#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

# --- Classes ---

orec:Skill a owl:Class ;
    rdfs:comment "A technical, behavioral, or domain skill" ;
    rdfs:label "Skill" .

orec:Requisition a owl:Class ;
    rdfs:comment "A job opening being recruited for" ;
    rdfs:label "Requisition" .

orec:Round a owl:Class ;
    rdfs:comment "An interview round within a requisition plan" ;
    rdfs:label "Round" .

orec:Competency a owl:Class ;
    rdfs:comment "A specific evaluation dimension assessed in a round" ;
    rdfs:label "Competency" .

orec:Candidate a owl:Class ;
    rdfs:comment "A candidate being evaluated. Name visible at org level, stripped for cross-org benchmarks." ;
    rdfs:label "Candidate" .

orec:Interviewer a owl:Class ;
    rdfs:comment "A person who conducts interviews" ;
    rdfs:label "Interviewer" .

orec:Company a owl:Class ;
    rdfs:comment "An organization referenced in interviews" ;
    rdfs:label "Company" .

orec:RolePattern a owl:Class ;
    rdfs:comment "An emergent archetype across similar requisitions" ;
    rdfs:label "RolePattern" .

orec:Location a owl:Class ;
    rdfs:comment "A geographic location for a requisition or candidate" ;
    rdfs:label "Location" .

orec:Trait a owl:Class ;
    rdfs:comment "A behavioral pattern or work-style attribute observed in a candidate" ;
    rdfs:label "Trait" .

# --- Object Properties (Relationships) ---

orec:requires a owl:ObjectProperty ;
    rdfs:domain orec:Requisition ;
    rdfs:range orec:Skill ;
    rdfs:comment "Skill required by a requisition" .

orec:hasRound a owl:ObjectProperty ;
    rdfs:domain orec:Requisition ;
    rdfs:range orec:Round ;
    rdfs:comment "Round in a requisition interview plan" .

orec:assesses a owl:ObjectProperty ;
    rdfs:domain orec:Round ;
    rdfs:range orec:Competency ;
    rdfs:comment "Competency assessed by this round" .

orec:demonstrated a owl:ObjectProperty ;
    rdfs:domain orec:Candidate ;
    rdfs:range orec:Skill ;
    rdfs:comment "Skill demonstrated by candidate with evidence" .

orec:conducted a owl:ObjectProperty ;
    rdfs:domain orec:Interviewer ;
    rdfs:range orec:Round ;
    rdfs:comment "Interviewer conducted this round" .

orec:workedAt a owl:ObjectProperty ;
    rdfs:domain orec:Candidate ;
    rdfs:range orec:Company ;
    rdfs:comment "Candidate previous employer" .

orec:predictsSuccess a owl:ObjectProperty ;
    rdfs:domain orec:Skill ;
    rdfs:range orec:RolePattern ;
    rdfs:comment "Skill that correlates with hire outcomes for this role pattern" .

orec:locatedIn a owl:ObjectProperty ;
    rdfs:domain orec:Requisition ;
    rdfs:range orec:Location ;
    rdfs:comment "Geographic location for a requisition" .

orec:basedIn a owl:ObjectProperty ;
    rdfs:domain orec:Candidate ;
    rdfs:range orec:Location ;
    rdfs:comment "Candidate geographic base, extracted from transcripts/JDs" .

orec:exhibits a owl:ObjectProperty ;
    rdfs:domain orec:Candidate ;
    rdfs:range orec:Trait ;
    rdfs:comment "Behavioral trait observed across candidate interactions" .

orec:withdrewFrom a owl:ObjectProperty ;
    rdfs:domain orec:Candidate ;
    rdfs:range orec:Requisition ;
    rdfs:comment "Candidate withdrew from a requisition" .

orec:defaultFor a owl:ObjectProperty ;
    rdfs:domain orec:Interviewer ;
    rdfs:range orec:Round ;
    rdfs:comment "Interviewer pre-assigned to this round type" .

# --- Datatype Properties ---

orec:rating a owl:DatatypeProperty ;
    rdfs:domain orec:Candidate ;
    rdfs:range xsd:string ;
    rdfs:comment "Interview round rating: strong_yes, yes, maybe, no, strong_no" .

orec:evidenceQuote a owl:DatatypeProperty ;
    rdfs:range xsd:string ;
    rdfs:comment "Direct quote from transcript supporting a claim" .

orec:evidenceStatus a owl:DatatypeProperty ;
    rdfs:range xsd:string ;
    rdfs:comment "Evidence validation: supported, contradicted, partial, none" .

orec:confidence a owl:DatatypeProperty ;
    rdfs:range xsd:float ;
    rdfs:comment "Confidence score for derived relationships" .

orec:experienceMinYears a owl:DatatypeProperty ;
    rdfs:domain orec:Requisition ;
    rdfs:range xsd:integer ;
    rdfs:comment "Minimum years of experience required" .

orec:experienceMaxYears a owl:DatatypeProperty ;
    rdfs:domain orec:Requisition ;
    rdfs:range xsd:integer ;
    rdfs:comment "Maximum years of experience required" .

orec:experienceYears a owl:DatatypeProperty ;
    rdfs:domain orec:Candidate ;
    rdfs:range xsd:integer ;
    rdfs:comment "Candidate experience years, inferred from requisition or transcript" .
```

This TTL file is the **single source of truth**. From it, we generate:
1. Pydantic entity models (for validation)
2. Graphiti `entity_types` dict (for extraction constraints)
3. Graphiti `edge_type_map` dict (for relationship constraints)
4. Supabase `brain_ontology` rows (for runtime queries)
5. Text2Cypher schema (for query generation)

---

## Ingestion Pipeline

### SQS Event Schema

```json
{
    "event_id": "evt-uuid",
    "event_type": "feedback_completed",
    "ingestion_mode": "triplet",
    "org_id": "org-uuid",
    "timestamp": "2026-05-03T10:30:00Z",
    "source_ref": {
        "candidate_round_id": "cr-uuid",
        "requisition_id": "req-uuid",
        "candidate_id": "cand-uuid"
    },
    "payload": {}
}
```

| event_type | ingestion_mode | emitted_by | payload |
|---|---|---|---|
| `feedback_completed` | `triplet` | Feedback Agent Lambda | `{}` (Lambda fetches from Supabase) |
| `plan_created` | `triplet` | Intake Agent Lambda | `{}` (Lambda fetches from Supabase) |
| `decision_made` | `triplet` | Backend API | `{verdict, outcome_notes}` |
| `candidate_withdrawn` | `triplet` | Backend API | `{}` — emitted when `candidates.status` set to `withdrawn` |
| `backfill_feedback` | `triplet` | Data eng script | `{candidate_round_id}` |
| `backfill_plan` | `triplet` | Data eng script | `{requisition_id}` |
| `transcript_available` | `episodic` | Feedback Agent Lambda | `{}` — fetches `recall_bots.transcript_data` + `participant_utterances` |
| `scorecard_available` | `episodic` | Backend API | `{}` — fetches `candidate_rounds.scorecard_transcript` (interviewer verbal debrief) |
| `intake_research_available` | `episodic` | Intake Agent Lambda | `{}` — fetches `requisitions.intake_transcript` (structured research, ~9K chars) |
| `jd_available` | `episodic` | Intake Agent Lambda / Backend API | `{}` — fetches `requisitions.job_description`. Rich JD text with responsibilities, requirements, company context, tech stack. Populates Company, Skill, domain context entities. |
| `question_summaries_available` | `episodic` | Feedback Agent Lambda | `{}` — fetches `candidate_rounds.question_summaries` (JSONB). Per-competency rich narratives with behavioral observations, strategic thinking patterns, and work-style signals not captured in structured feedback. Populates Trait entities. |
| `debrief_recorded` | `episodic` | Future: Recall bot | `{transcript_text}` |
| `slack_interaction` | `episodic` | Slack Agent | `{messages}` |

### Triplet Ingestion Path (Structured Data)

When `ingestion_mode == "triplet"`, the Lambda builds `EntityNode` and `EntityEdge` objects from structured data and calls `graphiti.add_triplet()`.

**Example: Feedback Packet → Triplets**

```python
async def ingest_feedback_triplets(
    graphiti: Graphiti,
    candidate_round: dict,
    round_info: dict,
    requisition: dict,
    feedback_items: list[dict],
    org_id: str,
):
    candidate_node = EntityNode(
        name=f"Candidate_{candidate_round['candidate_id'][:8]}",
        labels=["Entity", "Candidate"],
        group_id=org_id,
        summary=candidate_round.get("summary", ""),
        attributes={"status": candidate_round.get("status")},
    )

    round_node = EntityNode(
        name=round_info["name"],
        labels=["Entity", "Round"],
        group_id=org_id,
        attributes={
            "category": round_info.get("category"),
            "duration_minutes": round_info.get("duration_minutes"),
        },
    )

    requisition_node = EntityNode(
        name=requisition["role_title"],
        labels=["Entity", "Requisition"],
        group_id=org_id,
        attributes={"status": requisition.get("status")},
    )

    edges = []

    # Candidate → Round (interview event with rating)
    edges.append(build_edge(
        source=candidate_node,
        target=round_node,
        name="INTERVIEWED_IN",
        fact=f"Candidate received {candidate_round['rating']} rating "
             f"in {round_info['name']} round",
        attributes={
            "rating": candidate_round["rating"],
            "rating_numeric": RATING_MAP[candidate_round["rating"]],
        },
        valid_at=candidate_round.get("completed_at"),
    ))

    # Competency demonstrations from feedback items
    for item in feedback_items:
        if item["evidence_status"] in ("supported", "partial"):
            competency_node = EntityNode(
                name=item["heading"],
                labels=["Entity", "Competency"],
                group_id=org_id,
            )
            sentiment_rel = "STRONG_IN" if item["sentiment"] == "positive" else "WEAK_IN"
            edges.append(build_edge(
                source=candidate_node,
                target=competency_node,
                name=sentiment_rel,
                fact=item["feedback_text"],
                attributes={
                    "evidence": item.get("evidence", []),
                    "evidence_status": item["evidence_status"],
                },
                valid_at=candidate_round.get("completed_at"),
            ))

    # Ingest via add_triplet (no LLM cost, gets entity resolution)
    for edge in edges:
        await graphiti.add_triplet(
            source_node=edge.source_node,
            edge=edge,
            target_node=edge.target_node,
        )
```

**Full mapping — Feedback Packet → Graph:**

| Source Field | → Graph Representation | Notes |
|---|---|---|
| `requisition.role_title` | `(:Requisition)` node with title, status | |
| `round.skills[]` | `(:Round)-[:ASSESSES]->(:Skill)` per skill | **PRIMARY skill source.** Rich domain arrays, e.g. `["API and service boundary design", "Scalability reasoning"]` |
| `requisition.must_have_skills[]` | `(:Requisition)-[:REQUIRES]->(:Skill)` per skill | Sparse: only 7/115 reqs populated. Supplement only. |
| `requisition.good_to_have_skills[]` | `(:Requisition)-[:NICE_TO_HAVE]->(:Skill)` per skill | Similarly sparse. |
| `round.name` | `(:Round)` node with category, duration | |
| `feedback_question.heading` | `(:Competency)` node | Maps to competencies, NOT skills |
| `round → feedback_question` | `(:Round)-[:ASSESSES]->(:Competency)` per competency | |
| `candidate_round.rating` | `(:Candidate)-[:INTERVIEWED_IN {rating}]->(:Round)` | |
| `candidate_round.summary` | Stored in edge `fact` field | |
| `candidate_round.interviewer_email` | `(:Interviewer)-[:CONDUCTED]->(:Round)` | Resolution key for InterviewerEntity |
| `candidate_round.scorecard_transcript` | Episodic source → LLM extraction | Interviewer verbal debrief. New event: `scorecard_available` |
| `candidate_round.competency_snapshots` | `(:Candidate)-[:STRONG_IN/:WEAK_IN]->(:Competency)` with temporal snapshot | Point-in-time competency state (JSONB) |
| `candidate_feedback.feedback_text` | `(:Candidate)-[:STRONG_IN/:WEAK_IN]->(:Competency)` per item | NOT Candidate→Skill. Structured data is competency-level. |
| `candidate_feedback.evidence[]` | Stored in edge `attributes.evidence` | 3-5 transcript quotes each |
| `candidate_feedback.evidence_status` | Stored in edge `attributes.evidence_status` | supported, contradicted, partial, none |
| `candidate_round.question_summaries` | Episodic source → LLM extraction | Per-competency rich narratives. New event: `question_summaries_available`. Populates Trait entities and nuanced Competency signals beyond formal feedback. |
| `candidate.final_verdict` | `(:Candidate)-[:HIRED_BY/:REJECTED_BY]->(:Requisition)` | |
| `candidate.status = withdrawn` | `(:Candidate)-[:WITHDREW_FROM {date}]->(:Requisition)` | 8 candidates in production. Distinct from rejection — candidate-initiated. |

**Full mapping — Interview Plan → Graph:**

| Source Field | → Graph Representation | Notes |
|---|---|---|
| `requisition.role_title` | `(:Requisition)` node (resolves to existing via MERGE) | |
| `requisition.experience_min_years` | Stored in Requisition node `attributes.experience_min_years` | Populated on ALL 115 reqs. Enables experience-based queries. |
| `requisition.experience_max_years` | Stored in Requisition node `attributes.experience_max_years` | |
| `requisition.role_location` | `(:Requisition)-[:LOCATED_IN]->(:Location)` | Triplet. Values: "Remote", "Bangalore", "New York", etc. |
| `round.name, category` | `(:Round)` node, linked via `(:Requisition)-[:HAS_ROUND]->(:Round)` | Normalize category: "behavioural"→"behavioral", "Behavioral"→"behavioral" |
| `round.skills[]` | **PRIMARY.** `(:Round)-[:ASSESSES]->(:Skill)` per skill | Rich domain arrays, e.g. `["Database schema and storage trade-offs"]` |
| `round.guidelines[]` | Stored in Round node `attributes.guidelines` | Structured interviewer guidelines. Used for coaching signal: compare guidelines given vs. behavior in transcript. |
| `round.default_interviewer_emails` | `(:Interviewer)-[:DEFAULT_FOR]->(:Round)` per email | Pre-assigned panel structure. Triplet. |
| `requisition.must_have_skills[]` | `(:Requisition)-[:REQUIRES]->(:Skill)` | Sparse (7/115 populated). Supplement only. |
| `feedback_question.heading` | `(:Competency)` + `(:Round)-[:ASSESSES]->(:Competency)` | **787 unique headings** — requires competency resolution preprocessing (see below). |
| `requisition.job_description` | Episodic source → LLM extraction | Rich JD text with responsibilities, requirements, company context. New event: `jd_available`. Populates Company, Skill, domain context. |
| `requisitions.intake_transcript` | Episodic source → LLM extraction | Structured research doc (~9K chars). Surfaces Team, Company, RolePattern entities. |

**Full mapping — Decision → Graph:**

| Source Field | → Graph Representation |
|---|---|
| `candidate.final_verdict = hire` | `(:Candidate)-[:HIRED_BY {verdict, date}]->(:Requisition)` |
| `candidate.final_verdict = no_hire` | `(:Candidate)-[:REJECTED_BY {verdict, date}]->(:Requisition)` |
| `candidate.status = withdrawn` | `(:Candidate)-[:WITHDREW_FROM {date}]->(:Requisition)` |
| `candidate_round.outcome = advance` | `(:Candidate)-[:ADVANCED_FROM {date}]->(:Round)` |
| `candidate_round.outcome = reject` | `(:Candidate)-[:ELIMINATED_AT {date}]->(:Round)` |

### Episodic Ingestion Path (Unstructured Data)

> **UPDATED 2026-05-05:** The naive `add_episode()` approach below is superseded by the
> **identity-anchored episodic pipeline** defined in
> `docs/superpowers/specs/2026-05-05-episodic-ingestion-design.md`.
>
> Key change: episodic ingestion does NOT use raw `add_episode()` for the full pipeline.
> Instead, it uses LLM for concept extraction (Company, Trait, Market, Skill) but
> programmatically anchors all edges to deterministic identity nodes (Candidate, Interviewer,
> Requisition, Round) via `add_triplet()`. Every transcript comes with Supabase metadata
> (candidate_round_id → candidate_id, round_id, etc.) — the LLM never resolves identity,
> only discovers concepts. This prevents identity merging errors (e.g., two candidates
> named "Nitin" being merged). See the episodic spec for full details including
> source-specific handlers, metadata-anchored extraction, and backfill strategy.

When `ingestion_mode == "episodic"`, the service extracts concepts from text and anchors them to known identity nodes. The legacy `add_episode()` sketch below is kept for reference:

```python
# LEGACY SKETCH — see episodic-ingestion-design.md for actual implementation
async def ingest_episodic(
    graphiti: Graphiti,
    text: str,
    source_type: str,
    source_ref: dict,
    org_id: str,
    timestamp: datetime,
):
    await graphiti.add_episode(
        name=f"{source_type}_{source_ref.get('id', 'unknown')}",
        episode_body=text,
        source=EpisodeType.text,
        reference_time=timestamp,
        group_id=org_id,
        entity_types=ENTITY_TYPES,
        edge_type_map=EDGE_TYPE_MAP,
        source_description=f"Recruitment data: {source_type}. "
            "Extract skills, competencies, companies, team context, "
            "interviewer behaviors, candidate claims, and hiring signals. "
            "Every extracted entity must match the provided entity types.",
    )
```

**What episodic ingestion discovers that triplets miss:**

| Source | Signal Type | Example Discovery |
|---|---|---|
| Raw transcript | Unstated preferences | "Team seemed excited about her startup background" → Team VALUES StartupExperience |
| Raw transcript | Interviewer behavior | "Interviewer asked 4 leading questions" → Interviewer HAS_PATTERN LeadingQuestions |
| Raw transcript | Cross-candidate claims | Two candidates claim same project → entity resolution links them |
| Raw transcript | Skill evolution | "Used Kafka, recently switched to Pulsar" → temporal edge invalidation |
| Question summaries | Behavioral traits | "Managed global complexities in a checklist manner" → Candidate EXHIBITS SystematicExecutor |
| Question summaries | Strategic depth | "Has not yet developed a forward-looking North Star mindset" → Candidate WEAK_IN StrategicVision |
| Question summaries | Work style | "Communication tends toward detail-heavy explanations even when brevity is requested" → Candidate EXHIBITS VerboseCommunicator |
| Job description | Company context | "Northwind acquired Airbase" → Company KNOWN_FOR FinanceAutomation |
| Job description | Domain skills | "8+ years in B2B SaaS, platform product management" → RolePattern COMMONLY_REQUIRED B2BSaaS |
| Job description | Tech requirements | "Event-driven systems, APIs, data models" → Requisition REQUIRES specific technical Skills |
| Debrief meeting | Implicit criteria | "We need someone who can handle ambiguity" → RolePattern REQUIRES AmbiguityTolerance |
| Debrief meeting | Team dynamics | "Reporting to VP Eng, budget for 4 hires" → Team context nodes |
| Slack conversation | Recruiter patterns | "What worked for last backend hire?" → query pattern signals |
| Slack conversation | Pipeline intelligence | "Candidate X ghosted after offer" → Candidate WITHDREW_FROM Requisition |

### Backfill Pipeline

A data engineering script that reads all existing production data and emits SQS events. Uses the same pipeline as live data to ensure identical processing logic.

```python
async def backfill_all_production_data(supabase_client, sqs_client):
    # Phase 1: Backfill all requisitions (plans)
    requisitions = await supabase_client.table("requisitions") \
        .select("id, organization_id, role_title, status, created_at") \
        .in_("status", ["planned", "closed"]) \
        .execute()

    for req in requisitions.data:
        await sqs_client.send_message(
            QueueUrl=CORTEX_QUEUE_URL,
            MessageBody=json.dumps({
                "event_type": "backfill_plan",
                "ingestion_mode": "triplet",
                "org_id": req["organization_id"],
                "source_ref": {"requisition_id": req["id"]},
                "timestamp": req["created_at"],
            }),
        )

    # Phase 2: Backfill all completed feedback
    candidate_rounds = await supabase_client.table("candidate_rounds") \
        .select("id, candidate_id, round_id, rating, summary, completed_at") \
        .eq("status", "completed") \
        .not_.is_("rating", "null") \
        .execute()

    for cr in candidate_rounds.data:
        await sqs_client.send_message(
            QueueUrl=CORTEX_QUEUE_URL,
            MessageBody=json.dumps({
                "event_type": "backfill_feedback",
                "ingestion_mode": "triplet",
                "org_id": cr["organization_id"],
                "source_ref": {"candidate_round_id": cr["id"]},
                "timestamp": cr["completed_at"],
            }),
        )

    # Phase 3: Backfill decisions
    candidates = await supabase_client.table("candidates") \
        .select("id, requisition_id, status, final_verdict, updated_at") \
        .in_("status", ["hired", "rejected"]) \
        .execute()

    for cand in candidates.data:
        await sqs_client.send_message(
            QueueUrl=CORTEX_QUEUE_URL,
            MessageBody=json.dumps({
                "event_type": "backfill_decision",
                "ingestion_mode": "triplet",
                "org_id": cand["organization_id"],
                "source_ref": {"candidate_id": cand["id"]},
                "timestamp": cand["updated_at"],
            }),
        )
```

---

## Graphiti Configuration

### Initialization

```python
from graphiti_core import Graphiti
from graphiti_core.llm_client import AnthropicClient
from graphiti_core.embedder import OpenAIEmbedder

graphiti = Graphiti(
    neo4j_uri=os.environ["NEO4J_URI"],
    neo4j_user=os.environ["NEO4J_USER"],
    neo4j_password=os.environ["NEO4J_PASSWORD"],
    llm_client=AnthropicClient(
        model="claude-sonnet-4-6",
        api_key=os.environ["ANTHROPIC_API_KEY"],
    ),
    embedder=OpenAIEmbedder(
        model="text-embedding-3-small",
        api_key=os.environ["OPENAI_API_KEY"],
    ),
)

await graphiti.build_indices_and_constraints()
```

### Entity Types Registration

```python
ENTITY_TYPES = {
    "Skill": SkillEntity,
    "Requisition": RequisitionEntity,
    "Round": RoundEntity,
    "Competency": CompetencyEntity,
    "Candidate": CandidateEntity,
    "Interviewer": InterviewerEntity,
    "Company": CompanyEntity,
    "RolePattern": RolePatternEntity,
    "Team": TeamEntity,
    "Location": LocationEntity,
    "Trait": TraitEntity,
}
```

### Multi-Tenancy

Every Graphiti call includes `group_id=org_id`:
- `add_episode(... group_id=org_id)`
- `add_triplet()` — set `group_id` on both source and target EntityNodes
- `search(... group_ids=[org_id])`

For industry benchmarking, search with `group_ids=[org_id_1, org_id_2, ...]` across consented orgs.

### Search Configuration

```python
from graphiti_core.search.search_config import SearchConfig
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_RRF,
    NODE_HYBRID_SEARCH_RRF,
)

CORTEX_SEARCH_CONFIG = SearchConfig(
    edge_config=EDGE_HYBRID_SEARCH_RRF,
    node_config=NODE_HYBRID_SEARCH_RRF,
    limit=20,
)
```

---

## Intelligence Layer

All intelligence layer tables in Supabase PostgreSQL are **unchanged from V1**. See the original spec for full SQL CREATE statements.

### Tables Summary

| Table | Purpose |
|---|---|
| `brain_signals` | Every measurable observation from any data source |
| `brain_insights` | Computed intelligence from recipes and emergent detection |
| `brain_ontology` | Runtime ontology (synced from TTL source file) |
| `brain_interviewer_profiles` | Interviewer calibration, behavior patterns, effectiveness |
| `brain_human_corrections` | Recruiter feedback loop with lifecycle tracking |
| `brain_notifications` | Delivery tracking and dedup |
| `brain_state` | Per-org health and trigger readiness |
| `brain_event_log` | Audit trail for every Cortex operation |
| `brain_insight_evaluations` | Self-evaluation accuracy tracking |
| `brain_global.signal_aggregates` | Cross-company anonymized benchmarks |
| `brain_global.org_consent` | Benchmarking network opt-in |

### Signal Flow (Post-Ingestion)

After every ingestion (triplet or episodic), the Lambda:

1. Writes `brain_signals` from graph entities/edges created
2. Matches insight recipes against the event type
3. Computes insights if recipe conditions are met
4. Updates `brain_interviewer_profiles` if interviewer data present
5. Routes notifications (immediate or queued for digest)
6. Self-evaluates past predictions against new signals
7. Updates `brain_state` counters
8. Logs to `brain_event_log`

### Insight Recipes

Unchanged from V1. See original spec for full recipe definitions.

**Phase 1** (from first interview): coverage_gap_check, candidate_signal_summary, evidence_density_check
**Phase 2** (30+ interviews): calibration_shift, competency_weight_update, candidate_rank_change
**Phase 3** (100+ interviews): question_effectiveness, interviewer_panel_optimization, process_bottleneck_detection

---

## Query Interfaces

### 1. "Ask Cortex" (Natural Language → Graph)

```python
async def ask_cortex(question: str, org_id: str, graphiti: Graphiti):
    query_type = await classify_query(question)

    graph_results = await graphiti._search(
        query=question,
        group_ids=[org_id],
        config=CORTEX_SEARCH_CONFIG,
    )

    insights = await get_relevant_insights(question, org_id)
    profiles = await get_relevant_interviewer_profiles(question, org_id)
    benchmarks = await get_benchmarks_if_enrolled(question, org_id)

    return await synthesize_answer(
        question=question,
        graph_facts=[r.fact for r in graph_results],
        insights=insights,
        profiles=profiles,
        benchmarks=benchmarks,
        instruction="Cite specific evidence for every claim. "
                    "Include confidence levels. "
                    "If sample size is small, say so explicitly.",
    )
```

**Example queries:**

| Question | How Graph Answers |
|---|---|
| "Why are we losing candidates in Round 2?" | Aggregate `ELIMINATED_AT` edges by competency for round_number=2 |
| "Which interviewers give the most useful feedback?" | Query brain_interviewer_profiles by evidence_density |
| "What skills predict success for backend roles?" | Traverse `PREDICTS_SUCCESS` edges from Skills to RolePattern |
| "How does our time-to-fill compare to industry?" | Cross-org query on brain_global.signal_aggregates |
| "Which candidates should we re-engage for the new req?" | Find `REJECTED_BY` candidates whose skills overlap new req's `REQUIRES` edges |

### 2. REST API

```
GET  /cortex/signals?entity_type=candidate_round&entity_id={id}
GET  /cortex/insights?type=competency_weight&role_pattern={pattern}
GET  /cortex/entities/{id}/neighborhood?depth=2
GET  /cortex/query?q={natural_language_question}
GET  /cortex/health?org_id={id}
GET  /cortex/interviewer/{id}/profile
GET  /cortex/benchmarks?metric=time_to_fill&role_pattern={pattern}
POST /cortex/corrections
POST /cortex/ingest
```

---

## Industry Benchmarking Network

### What's Benchmarkable

| Metric | Min Orgs |
|---|---|
| Time-to-fill per role pattern | 5 |
| Rounds per role pattern | 5 |
| Pass-through rate per round type | 5 |
| Competency weight distribution per role pattern | 5 |
| Interviewer-to-candidate ratio | 5 |
| Question effectiveness scores | 10 |
| Sourcing channel effectiveness | 10 |

### Candidate Identity: Two-Layer Model

Candidates use a **two-layer identity model** — names at org level, anonymized for cross-org:

**Org level (group_id = org_id):**
- Candidate node stores `name` (e.g., "Ankit Dalal") from `candidates.name`
- Name is visible in all org-scoped queries via `graphiti.search(group_ids=[org_id])`
- Enables actionable queries: "who should we re-engage?", "how did Ankit do across rounds?"
- Name is the entity resolution key within an org (same person applying to multiple reqs)

**Cross-org (Tier 3 benchmarks):**
- Nightly aggregation strips `name` — only `candidate_ref` (hashed ID) survives
- No PII crosses the org boundary
- Only aggregate patterns are promoted: "candidates with 5+ years who scored strong_yes on System Design had 80% hire rate across 12 orgs"

**InterviewerEntity** follows the same model: `interviewer_email` is hashed for the graph (`interviewer_ref`), but the email is retrievable within the org for coaching and assignment queries. Cross-org aggregation uses only the hash.

### Privacy Guarantees

- **k-anonymity (k >= 5):** No metric published with fewer than 5 contributing organizations
- **Differential privacy (epsilon = 1.0):** Laplace noise on numeric aggregates
- **PII scrubbing:** Candidate names and interviewer emails stripped before cross-org aggregation. Only hashed refs and aggregate patterns survive.
- **No individual tracing:** Cross-org queries return aggregates only
- **Org-level identity:** Names visible only within the org's own group_id scope

---

## Service Architecture

### Single Service: `cortex-backend`

One FastAPI service handles all Cortex workloads — real-time SQS ingestion, backfill, nightly cron jobs, and the query API. Runs as a Docker container in `backend-deploy/docker-compose.yml` alongside the existing backend, slack-agent, and voice-agent.

**Why not Lambda:** At current volume (~100 events/day, ~1,900 nodes), Lambda adds deployment friction and cold-start latency on Neo4j connections without meaningful scaling benefit. A single long-running service keeps one Graphiti connection pool, one test suite, and one deployment path. If volume grows to 10K+ events/day, the SQS consumer can be extracted to Lambda without changing the processing code.

```
cortex-backend/
├── app/
│   ├── main.py                  # FastAPI startup: Graphiti init, SQS consumer, scheduler
│   ├── config.py                # Env vars (NEO4J_URI, SQS_QUEUE_URL, SUPABASE_URL, etc.)
│   ├── graphiti_client.py       # Singleton Graphiti instance, initialized once at startup
│   │
│   ├── ontology/                # The constraint envelope
│   │   ├── recruitment.ttl      # TTL source of truth
│   │   ├── entity_types.py      # Pydantic models + ENTITY_TYPES dict
│   │   ├── edge_type_map.py     # EDGE_TYPE_MAP dict
│   │   └── normalizers.py       # Competency alias resolution, category normalization
│   │
│   ├── ingestion/               # Event processing
│   │   ├── event_processor.py   # Ingests one claimed cortex_events row: route to handlers
│   │   ├── router.py            # event_type → handler dispatch
│   │   ├── fetchers.py          # Supabase queries to hydrate events
│   │   ├── triplet_builders.py  # Structured data → EntityNode + EntityEdge
│   │   ├── episodic_handlers.py # Text sources → add_episode() calls
│   │   └── backfill.py          # Reads Supabase history, processes directly or via SQS
│   │
│   ├── intelligence/            # Post-ingestion processing
│   │   ├── signals.py           # Write brain_signals after ingestion
│   │   ├── recipes.py           # Insight recipe matching + computation
│   │   └── scheduler.py         # APScheduler cron: nightly aggregation, tier promotion, cleanup
│   │
│   └── api/                     # Query interfaces
│       ├── health.py            # GET /health (graph stats, queue depth)
│       ├── query.py             # GET /cortex/query (Ask Cortex)
│       └── backfill.py          # POST /cortex/backfill (trigger backfill via API)
│
├── tests/
├── Dockerfile
└── requirements.txt
```

### Three Runtime Modes in One Process

| Mode | Trigger | What It Does |
|------|---------|------------|
| **SQS Consumer** | Long-poll loop, always running | Receives events from SQS, routes to triplet builders or episodic handlers, writes to Neo4j |
| **Backfill** | API call or CLI command | Reads historical Supabase data, processes through the same builders/handlers directly (no SQS needed for local dev) |
| **Scheduler** | APScheduler cron | Nightly jobs: tier promotion checks, benchmark aggregation, stale entity cleanup, ontology sync |

All three share the same Graphiti client, Supabase client, ontology, and normalizers. One Docker container, one connection pool, one test suite.

### Event Emitters (Changes to Existing Services)

No new services for triggering. Each existing service gets a small SQS publish call after its current work completes:

| Existing Service | When | Event Emitted |
|---|---|---|
| Feedback Agent Lambda | After writing feedback to Supabase | `feedback_completed` (triplet), `question_summaries_available` (episodic), `transcript_available` (episodic) |
| Intake Agent Lambda | After writing plan + rounds | `plan_created` (triplet), `intake_research_available` (episodic), `jd_available` (episodic, if JD exists) |
| Backend API | On candidate decision | `decision_made` (triplet) |
| Backend API | On candidate withdrawal | `candidate_withdrawn` (triplet) |
| Backend API | On scorecard submission | `scorecard_available` (episodic) |

Emitters are wired up **after** the Cortex service is working with backfill. Debug one thing at a time.

### Deployment

```yaml
# backend-deploy/docker-compose.yml (addition)
cortex:
  build: ../../cortex-backend
  env_file: ../.env-cortex
  depends_on:
    - caddy
  restart: unless-stopped
  # No port exposure — communicates via SQS (inbound) and Supabase/Neo4j (outbound)
  # Health check via internal Docker network if needed
```

Env vars in `deploy-config/.env-cortex`: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SQS_QUEUE_URL`, `AWS_REGION`.

Local development: `uvicorn app.main:app --reload` — no Docker or SQS needed. Backfill runs in "direct" mode (processes inline), Graphiti connects to Neo4j Aura Free.

### Backfill: Two Modes

| Mode | Use Case | How It Works |
|------|----------|------------|
| **Direct** (local dev) | Testing builders + graph population without SQS | Reads Supabase → calls triplet builders / episodic handlers → writes to Neo4j directly |
| **SQS** (production) | Full pipeline test, same path as real-time | Reads Supabase → emits SQS events → Cortex service consumes and processes them |

Both modes produce identical graph output. Direct mode skips the queue for faster iteration.

**Backfill phase ordering** (requisition skeleton must exist before feedback references it):
1. Plans → Requisition, Round, Skill, Location, default interviewers
2. Feedback → Candidate, Competency, INTERVIEWED_IN, STRONG_IN/WEAK_IN
3. Decisions + Withdrawals → HIRED_BY, REJECTED_BY, WITHDREW_FROM
4. Job descriptions → episodic: Company, domain Skills, market context
5. Question summaries → episodic: Traits, nuanced competency signals

### Nightly Cron Jobs

| Job | Schedule | Purpose |
|-----|----------|---------|
| Tier promotion | Daily 2 AM | Count orgs using equivalent ontology terms, promote to Tier 3 at 5+ orgs |
| Benchmark aggregation | Daily 3 AM | Cross-org metrics for opted-in orgs, differential privacy, write to brain_global |
| Stale entity cleanup | Weekly | Remove provisional ontology terms never confirmed by humans |
| Ontology sync | Daily | Sync TTL source → brain_ontology Supabase table |

## Implementation Timeline

### Week 1: Foundation

**Goal:** Service running, ontology defined, historical data backfilled, graph queryable.

- [ ] Service skeleton: FastAPI + Graphiti init + `/health` endpoint
- [ ] Ontology files: entity_types.py, edge_type_map.py, recruitment.ttl
- [ ] Competency resolution: one-time script → `competency_aliases.json` (787 → ~200-300 canonical)
- [ ] Category normalization mapping
- [ ] Triplet builders: plan, feedback, decision, withdrawal
- [ ] Fetchers: Supabase queries to hydrate events
- [ ] Neo4j Aura Free instance
- [ ] Backfill (direct mode) — populate graph with all historical data
- [ ] Validate with Cypher queries in Neo4j browser

### Week 2-3: Live Pipeline

**Goal:** Real-time events flow through SQS into the graph.

- [ ] SQS queue `cortex-ingestion-events` + DLQ
- [ ] SQS consumer + event router
- [ ] Episodic handlers: question_summaries, JD, transcript, scorecard, intake
- [ ] Backfill (SQS mode) — test full pipeline end-to-end
- [ ] Docker container in backend-deploy compose
- [ ] Wire emitters in: Feedback Lambda, Intake Lambda, Backend API
- [ ] Deploy Supabase migrations for brain_* tables
- [ ] brain_signals + brain_state + brain_event_log

### Month 2: Intelligence + Ask Cortex

**Goal:** First insight recipes active. Natural language query interface.

- [ ] Activate Phase 1 insight recipes
- [ ] brain_ontology sync (TTL → Supabase)
- [ ] Ontology lifecycle: new term validation flow
- [ ] Scheduler: nightly cron jobs
- [ ] "Ask Cortex" query endpoint
- [ ] PII scrubbing for cross-org path

### Month 3-4: Full Intelligence

**Goal:** Cortex Agent running. Proactive insights. Interviewer profiles.

- [ ] Cortex Agent OODA loop
- [ ] Phase 2 recipes
- [ ] Interviewer profile computation
- [ ] Human correction pipeline
- [ ] Notification router (Slack DM + digest)
- [ ] Ask Cortex in Slack agent and Brain UI

### Month 5-6: Benchmarking + Emergent Patterns

**Goal:** Industry network live. Emergent pattern detection.

- [ ] Emergent pattern detection (community detection + hypothesis generation)
- [ ] Phase 3 recipes
- [ ] Benchmarking consent flow
- [ ] Cross-org aggregation pipeline
- [ ] Benchmarking API endpoints

### Trigger-Based Additions

| Trigger | Condition | Addition | Cost |
|---|---|---|---|
| Emergent Detection | 200+ interviews | Community detection + hypothesis generation | ~$2/mo |
| Fine-tuned Extraction | 1,000+ verified extractions | Gemma 4 E4B LoRA | $0.50/run |
| Audio Intelligence | Voice agent stable + 20 calls/week | Pyannote + prosody Lambda | ~$5/mo |
| Cross-Company | 5+ orgs with 100+ interviews + legal | Nightly anonymized aggregation | ~$5/mo |
| Ontology Classifier | 500+ human corrections | Qwen3 4B LoRA | $0.50/run |
| Neo4j Upgrade | 150K entities or customer-facing | Aura Free → Professional | $65/mo |

---

## Cost Estimates

| Phase | Monthly Cost | What's Running |
|---|---|---|
| Week 1-3 (Foundation) | ~$5-15 | Neo4j Aura Free + Supabase (existing) + Cortex service in Docker |
| Month 2 (Episodic + Intelligence) | ~$15-50 | + LLM extraction for transcripts |
| Month 3-4 (Full Intelligence) | ~$20-60 | + Cortex Agent LLM calls + notifications |
| Month 5-6 (Benchmarking) | ~$25-70 | + cross-org aggregation |
| Full Cortex | ~$100-200/mo | Everything |

**Key cost insight:** Triplet ingestion is $0 LLM cost. Only episodic ingestion and intelligence computation incur LLM costs.

---

## Production Data Validation (2026-05-03)

Validated the ontology schema and ingestion design against actual Supabase production data. Queried all relevant tables to verify data shapes, field availability, and capacity estimates.

### Production Data Counts

| Table | Count | Notes |
|---|---|---|
| `requisitions` | 115 | Across 5 organizations |
| `rounds` | 645 | ~5.6 rounds per requisition average |
| `candidate_rounds` (rated) | 125 | Completed interviews with ratings |
| `candidate_feedback` | 349 | Feedback items with evidence arrays |
| `feedback_questions` | 3,141 | Competency definitions across all rounds |
| `candidates` (decided) | 11 | Final hire/no-hire decisions |
| `organizations` | 5 | Active organizations with data |

### Capacity Estimate (Post-Backfill)

| Entity Type | Estimated Count | Source |
|---|---|---|
| Requisition | ~115 | 1:1 with requisitions table |
| Round | ~645 | 1:1 with rounds table |
| Competency | ~200-300 | Deduplicated from 787 unique headings (1,857 active feedback_questions). Requires resolution preprocessing. |
| Candidate | ~240 | Unique candidates (221 active + 8 withdrawn + 7 hired + 4 rejected) |
| Skill | ~400-600 | Deduplicated from round.skills[] arrays |
| Interviewer | ~50-80 | Unique interviewer_email values |
| Location | ~30-50 | Deduplicated from requisitions.role_location values |
| Trait | ~0 (episodic-only) | Discovered from question_summaries and transcripts |
| Company | ~0 (episodic-only) | No structured company data; discovered from JDs and transcripts |
| Team | ~0 (episodic-only) | No structured team data in production |
| RolePattern | ~0 (emergent) | Discovered after community detection, not directly ingested |
| **Total Nodes** | **~1,900** | |

| Edge Type | Estimated Count | Source |
|---|---|---|
| INTERVIEWED_IN | ~125 | 1:1 with rated candidate_rounds |
| STRONG_IN / WEAK_IN | ~349 | 1:1 with candidate_feedback items |
| HAS_ROUND | ~645 | 1:1 with rounds |
| ASSESSES (Round→Competency) | ~3,141 | 1:1 with feedback_questions |
| ASSESSES (Round→Skill) | ~1,500 | ~2-3 skills per round from skills[] arrays |
| CONDUCTED | ~125 | 1:1 with rated rounds (via interviewer_email) |
| HIRED_BY / REJECTED_BY | ~11 | 1:1 with decided candidates |
| WITHDREW_FROM | ~8 | 1:1 with withdrawn candidates |
| LOCATED_IN | ~115 | 1:1 with requisitions (all have role_location) |
| DEFAULT_FOR | ~200-300 | From rounds.default_interviewer_emails arrays |
| REQUIRES / NICE_TO_HAVE | ~50 | Sparse — only 7/115 reqs have must_have_skills |
| **Total Edges** | **~6,400** | |

**Conclusion:** ~1,800 nodes + ~6,400 edges is well within Neo4j Aura Free limits (200K nodes, 400K relationships). Estimated 18+ months of runway before upgrade trigger.

### Schema Adjustments from Validation

#### 1. Skills live at Round level, not Requisition level

`requisitions.must_have_skills` is populated for only **7 of 115** requisitions. Meanwhile, `rounds.skills[]` contains rich, domain-specific skill arrays for nearly all rounds.

**Example `round.skills[]` values (production data):**
```json
["API and service boundary design", "Database schema and storage trade-offs", "Scalability and reliability reasoning"]
["Leadership in ambiguous situations", "Strategic trade-off communication", "Cross-functional influence"]
["Practical React fluency", "Component architecture clarity", "State management and data flow"]
```

**Impact:** The primary Skill ingestion path is `Round→ASSESSES→Skill`, not `Requisition→REQUIRES→Skill`. The requisition-level skill edges are a sparse supplement, not the backbone. Triplet ingestion must prioritize `round.skills[]`.

#### 2. Candidate→Skill is episodic-only (structured path is Candidate→Competency)

`candidate_feedback` maps to `feedback_questions.heading` — a **competency heading** like "Problem Decomposition" or "Code Quality", NOT a skill. Each feedback item contains 3-5 evidence quotes from the transcript.

**Example feedback item (production data):**
```json
{
  "heading": "Problem Decomposition",
  "feedback_text": "Candidate demonstrated strong ability to break down complex problems...",
  "evidence": ["Quote 1 from transcript...", "Quote 2...", "Quote 3..."],
  "evidence_status": "supported",
  "sentiment": "positive"
}
```

**Structured ingestion path:** `Candidate -[:STRONG_IN/:WEAK_IN]-> Competency` (from feedback).
**NOT:** `Candidate -[:DEMONSTRATED]-> Skill` — this relationship only emerges through episodic ingestion of raw transcripts where the LLM extracts skill mentions from conversation text.

#### 3. CompanyEntity and TeamEntity are episodic-only

No structured production fields carry past employer or team information. These entities populate exclusively through episodic ingestion of:
- Raw interview transcripts (candidate mentions past employers)
- Intake research documents (recruiter research on market context, competitive landscape)
- Scorecard transcripts (interviewer debriefs mentioning company context)

**Impact:** Zero Company/Team nodes after triplet-only backfill. They appear starting Month 2 when episodic ingestion activates.

### New Data Sources Discovered

#### `candidate_rounds.scorecard_transcript`

Interviewer's verbal debrief recorded after the interview. Rich unstructured text capturing what the interviewer says verbally vs. what they write formally. Valuable for interviewer calibration analysis — discrepancies between verbal and written feedback reveal bias patterns.

- **Ingestion mode:** Episodic
- **Event type:** `scorecard_available`
- **Unique signal:** Implicit criteria, team fit assessment, off-the-record impressions

#### `recall_bots.transcript_data` (JSONB)

Complete word-by-word interview transcript from Recall.ai bot recording with speaker diarization. Primary source for entities that can't be extracted from structured feedback.

- **Ingestion mode:** Episodic
- **Event type:** `transcript_available`
- **Related fields:** `participant_utterances` (JSONB, per-speaker segmented), `recording_duration_seconds`
- **Unique signal:** Candidate→Skill, Candidate→Company, interviewer behavior patterns, unstated preferences

#### `candidate_rounds.competency_snapshots` (JSONB)

Point-in-time snapshot of competency evaluations frozen at round completion. Structured data that can generate temporal `Candidate→Competency` edges.

- **Ingestion mode:** Triplet (structured JSONB)
- **Event type:** Included in `feedback_completed` event processing
- **Unique signal:** Temporal competency state — enables tracking how evaluations evolve across rounds

#### `requisitions.intake_transcript`

NOT a raw conversation transcript. This is a **structured research document** produced by the intake agent — contains role analysis, market context, competitive landscape, salary benchmarking, and sourcing strategy recommendations. Up to ~9,000 characters.

- **Ingestion mode:** Episodic
- **Event type:** `intake_research_available`
- **Unique signal:** Team, Company, RolePattern, and market context entities. Sections like "Role Analysis", "Market Context", "Sourcing Strategy" with detailed findings.

#### `candidate_rounds.question_summaries` (JSONB)

Per-competency rich narrative assessments generated by the feedback agent. Contains deeper behavioral signals than `candidate_feedback.feedback_text` — discusses approach quality, strategic thinking patterns, work-style observations, and implicit trait evaluations.

- **Ingestion mode:** Episodic
- **Event type:** `question_summaries_available`
- **Unique signal:** Behavioral traits (TraitEntity), nuanced competency assessments, work-style patterns

**Example question_summaries (production data):**
```json
{
  "1": "The candidate managed global complexities in a checklist manner rather than strategically. When asked for a globally scoped initiative, they initially selected a single-market example and required explicit redirection.",
  "2": "The candidate's strategic framing appears underdeveloped, likely shaped by working in top-heavy organizations with limited autonomy.",
  "3": "The candidate demonstrates outcome awareness by tracking concrete metrics—such as LLM API call growth from 200k to 1M monthly—but has not yet developed a strong forward-looking North Star mindset.",
  "4": "The candidate demonstrates strong cultural alignment with a feedback and learning mindset."
}
```

**Signals extractable that structured feedback misses:**
- Behavioral traits: "checklist manner", "limited autonomy", "strong learning orientation"
- Strategic depth: "underdeveloped strategic framing", "forward-looking North Star mindset"
- Work style: "detail-heavy explanations even when brevity is requested"
- Candidate context: "experience is primarily India-focused with limited North American market exposure"
- Implicit experience level: "operated more as executor than strategic leader" → seniority signal

#### `requisitions.job_description` (text)

Full job description text. Contains detailed responsibilities, required qualifications, tech stack, company context, and culture signals. Ranges from 500 to 5,000+ characters. Populated on requisitions sourced from external job boards.

- **Ingestion mode:** Episodic
- **Event type:** `jd_available`
- **Unique signal:** Company entity (employer brand, acquisition context), domain-specific Skills not in round.skills[], RolePattern context, experience requirements in prose form, geographic/market signals

**Example signals from production JDs:**
- Company context: "Northwind acquired Airbase" → CompanyEntity with acquisition relationship
- Domain skills beyond round.skills[]: "event-driven systems, APIs, data models" → specific technical Skills
- Market context: "India's 300 million-strong blue-collar workforce" → domain/market signal for RolePattern
- Experience granularity: "8+ years of Product Management experience in B2B SaaS, 2+ years in platform" → richer than `experience_min_years` integer

#### `requisitions.role_location` (varchar)

Structured location field on ALL requisitions. Values include "Remote", "Bangalore", "New York", etc.

- **Ingestion mode:** Triplet ($0)
- **Event type:** Included in `plan_created` and `backfill_plan` processing
- **Unique signal:** `(:Requisition)-[:LOCATED_IN]->(:Location)` edges enable geo-based analytics

#### `rounds.default_interviewer_emails` (ARRAY)

Pre-assigned interviewer emails per round type. Represents the organizational panel structure — which interviewers are designated for which round categories.

- **Ingestion mode:** Triplet ($0)
- **Event type:** Included in `plan_created` and `backfill_plan` processing
- **Unique signal:** `(:Interviewer)-[:DEFAULT_FOR]->(:Round)` edges. Enables "who was supposed to interview vs. who actually did" analysis when compared against `candidate_rounds.interviewer_email`.

#### `rounds.guidelines` (JSONB)

Structured interviewer guidelines with title + description pairs defining evaluation methodology.

- **Ingestion mode:** Triplet — stored in Round node `attributes.guidelines`
- **Event type:** Included in `plan_created` processing
- **Unique signal:** Defines expected interviewer behavior. Future coaching signal: compare guidelines given vs. actual behavior in transcript episodic extraction.

**Example (production data):**
```json
[
  {"title": "Start with problem clarification", "description": "Ensure candidate asks clarifying questions about constraints and edge cases"},
  {"title": "Evaluate approach before coding", "description": "Have candidate explain their approach before writing code"},
  {"title": "Assess time and space complexity", "description": "Ask candidate to analyze complexity of their solution"}
]
```

### Competency Resolution Strategy

Production data contains **787 unique competency headings** across 1,857 active feedback_questions. Many are near-duplicates that must be resolved before ingestion to avoid graph pollution.

**Scale of the problem:**
- Conflict cluster: "Conflict Resolution", "Conflict Handling", "Conflict Navigation", "Conflict & Alignment", "Conflict & Candor", "Conflict & Feedback", "Conflict De-escalation", "Conflict and Alignment", "Conflict and Ambiguity", "Conflict and Escalation" (10+ variants)
- Ownership cluster: "Ownership", "Ownership & Accountability", "Ownership Mentality", "Ownership Mindset", "Ownership Evidence", "End-to-End Ownership", "Ownership Orientation", "Ownership Signals", "Ownership Under Ambiguity" (12+ variants)
- AI cluster: "AI Curiosity", "AI Domain Depth", "AI Product Depth", "AI Systems Fluency", "AI Tool Fluency", "AI Strategy Vision", "AI Interaction Craft" (20+ variants)
- Communication cluster: "Communication", "Communication Clarity", "Communication Fluency", "Communication Skills", "Communication Structure", "Adaptive Communication", "Analytical Communication" (15+ variants)

**Resolution approach (runs as preprocessing before first backfill):**

1. **Embedding-based clustering:** Embed all 787 headings with text-embedding-3-small. Cluster at cosine similarity ≥ 0.85 threshold.
2. **Canonical name selection:** For each cluster, pick the shortest unambiguous heading as canonical (e.g., "Conflict Resolution" for the conflict cluster).
3. **LLM verification pass:** For borderline clusters (0.75–0.85 similarity), use Claude to confirm whether terms are truly equivalent or meaningfully distinct. Example: "Edge Case Handling" vs "Edge Case Awareness" — one is about catching them, the other about knowing they exist.
4. **Alias table:** Store all variants as aliases mapping to canonical competency in `brain_ontology`. Entity resolution in Graphiti uses this mapping.
5. **Category normalization:** Normalize round categories at the same time — "behavioural" → "behavioral", "Behavioral" → "behavioral", "Culture" → "culture".

**Expected output:** 787 unique headings → ~200-300 canonical competencies with alias mappings. This runs once before backfill and then feeds into the ontology lifecycle (new headings match against existing canonical terms before creating new entries).

### Round Category Normalization

Production data has 16 distinct category values with case and spelling inconsistencies:

| Production Value | Normalized Value | Count |
|---|---|---|
| `behavioral` | `behavioral` | 160 |
| `domain` | `domain` | 115 |
| `culture` | `culture` | 95+4 |
| `assessment` | `assessment` | 90 |
| `coding` | `coding` | 65 |
| `design` | `design` | 54 |
| `behavioural` | `behavioral` | 16 |
| `Behavioral` | `behavioral` | 2 |
| `Culture` | `culture` | 4 |
| `Presentation` | `presentation` | 2 |
| `Screen` | `screen` | 2 |
| `AI` | `domain` | 1 |
| `generic` | `generic` | 1 |
| `Problem-Solving` | `coding` | 1 |
| `Technical` | `coding` | 1 |
| `Product` | `domain` | 2 |

Normalization runs as preprocessing during triplet ingestion: lowercase, map variants to canonical values.

### Revised Data Source → Ingestion Mode Matrix

| Data Source | Mode | Entities Produced | Edge Types | Priority |
|---|---|---|---|---|
| `candidate_rounds` (rated) | Triplet | Candidate, Round, Interviewer | INTERVIEWED_IN, CONDUCTED | P0 — Week 1 backfill |
| `candidate_feedback` + `feedback_questions` | Triplet | Candidate, Competency | STRONG_IN, WEAK_IN, ASSESSES | P0 — Week 1 backfill |
| `rounds` + `rounds.skills[]` | Triplet | Round, Skill, Requisition | HAS_ROUND, ASSESSES | P0 — Week 1 backfill |
| `requisitions` (plan + location + experience) | Triplet | Requisition, Location, (sparse Skills) | REQUIRES, NICE_TO_HAVE, LOCATED_IN | P0 — Week 1 backfill |
| `candidates` (decided + withdrawn) | Triplet | Candidate, Requisition | HIRED_BY, REJECTED_BY, WITHDREW_FROM | P0 — Week 1 backfill |
| `rounds.default_interviewer_emails` | Triplet | Interviewer, Round | DEFAULT_FOR | P0 — Week 1 backfill |
| `competency_snapshots` | Triplet | Candidate, Competency | STRONG_IN, WEAK_IN (temporal) | P1 — Week 1 backfill |
| `question_summaries` | Episodic | Candidate, Trait, Competency | EXHIBITS, nuanced STRONG_IN/WEAK_IN | P1 — Week 1 backfill |
| `requisitions.job_description` | Episodic | Company, Skill, RolePattern, Location | REQUIRES, KNOWN_FOR, domain context | P1 — Week 1 backfill |
| `recall_bots.transcript_data` | Episodic | Candidate, Skill, Company, Interviewer, Location, Trait | DEMONSTRATED, WORKED_AT, BASED_IN, EXHIBITS, behavior patterns | P1 — Month 2 |
| `scorecard_transcript` | Episodic | Interviewer, Candidate, Competency | calibration signals, implicit criteria | P1 — Month 2 |
| `intake_transcript` | Episodic | Team, Company, RolePattern | market context, sourcing signals | P2 — Month 2 |
| `participant_utterances` | Episodic | Interviewer, Candidate | speaking patterns, engagement signals | P2 — Month 3 |
| Debrief meetings | Episodic | Team, RolePattern, Competency | implicit criteria, team dynamics | P3 — Month 5 |
| Slack conversations | Episodic | various | recruiter patterns, pipeline signals | P3 — Month 5 |

### InterviewerEntity Resolution

The primary resolution key for `InterviewerEntity` is `candidate_rounds.interviewer_email`. This email is hashed before storage in the graph to maintain anonymization:

```python
interviewer_ref = hashlib.sha256(interviewer_email.encode()).hexdigest()[:12]
```

Entity resolution across rounds uses this hashed ref, ensuring the same interviewer links across all their conducted rounds regardless of which requisition or candidate. Graphiti's entity resolution (embedding + LSH + LLM verify) handles cases where the same person appears with different email aliases.

---

## Key Decisions Log

| Decision | Chosen | Alternative | Reason |
|---|---|---|---|
| Graph engine | Graphiti + Neo4j | Native Neo4j only | Entity resolution, temporal edges, contradiction detection built-in. `add_triplet()` gives structured ingestion at $0. |
| Two ingestion modes | `add_triplet()` + `add_episode()` | `add_episode()` only | Structured data shouldn't go through LLM re-extraction. Triplet path is $0 and deterministic. |
| Ontology approach | TTL/OWL → entity_types + edge_type_map | JSON schema in source_description (V1) | GoingMeta best practice: formal ontology constrains extraction, validation, AND retrieval. |
| Ontology tiers | base / org / industry | Single universal | Dynamic per-org growth + benchmarking requires tiered model. |
| Ingestion trigger | SQS events with mode parameter | Synchronous API / inline | Decoupled, supports backfill, retry via DLQ. Matches existing Lambda patterns. |
| Backfill strategy | Same SQS pipeline as live data | Separate import script | Identical processing logic. Backfill events are just regular events. |
| GraphEngine interface | Use Graphiti API directly (drop Protocol) | Protocol abstraction (V1) | Abstraction adds complexity without current swap risk. |
| LLM for extraction | Claude Sonnet (via Graphiti) | GPT-4o | Consistent with stack. Graphiti supports Anthropic client. |
| Embeddings | text-embedding-3-small (OpenAI) | Anthropic embeddings | Mature, cheap, well-supported by Graphiti. |
| Primary skill source | `round.skills[]` | `requisition.must_have_skills[]` | Production data: must_have_skills populated on only 7/115 reqs. Round skills are rich domain-specific arrays. |
| Candidate→Skill path | Episodic-only (triplet uses Competency) | Direct triplet | Feedback data maps to competency headings, not skills. Skill extraction requires raw transcript LLM parsing. |
| Interviewer resolution key | `interviewer_email` (hashed) | Name-based | Email is the only reliable identifier in `candidate_rounds`. Hashed for anonymization. |
| Competency resolution | Embedding clustering + LLM verification before backfill | Rely on Graphiti entity resolution alone | 787 unique headings with 10+ variant clusters. Graphiti resolution would create hundreds of near-duplicate nodes. Preprocessing is cheaper and more reliable. |
| Location as entity | LocationEntity with LOCATED_IN/BASED_IN edges | Attribute on Requisition node | Entity enables geo-based traversal queries ("all reqs in Bangalore") vs. attribute requires property filtering on every query. |
| Traits vs Competencies | Separate TraitEntity (episodic-only) | Fold into CompetencyEntity | Traits describe "how" (work style), competencies describe "what we evaluate" — conflating them corrupts both the coaching and evaluation signals. |
| question_summaries ingestion | Episodic (new event type) | Skip, rely on candidate_feedback | question_summaries contain behavioral trait signals, strategic depth observations, and work-style patterns that candidate_feedback.feedback_text doesn't capture. |
| JD as data source | Episodic (new event type) | Skip, rely on round.skills[] | JDs contain company context, domain-specific skills beyond round.skills[], experience requirements in prose, and market signals that no other structured field carries. |
| Candidate withdrawal | WITHDREW_FROM edge (triplet) | Fold into REJECTED_BY | Withdrawal is candidate-initiated — fundamentally different signal from rejection. Important for pipeline intelligence ("why are we losing candidates?"). |
| Candidate identity | Two-layer: name at org, hashed ref at cross-org | Full anonymization everywhere | Org-level queries must be actionable ("re-engage Ankit"). Anonymization only matters at cross-org boundary. Graphiti group_id already enforces isolation. |
| Runtime architecture | Single FastAPI service (SQS consumer + cron + API) | Lambda per event | At ~100 events/day, Lambda adds cold-start friction and splits the codebase. One service = one connection pool, one test suite, one deploy. Extract to Lambda later if volume justifies. |

---

## Differences from V1

| Area | V1 (2026-04-13) | V2 (2026-05-03) | Reason |
|---|---|---|---|
| Ingestion | Single path: text → Graphiti | Two paths: triplet ($0) + episodic | Structured data doesn't need LLM extraction |
| Ontology format | JSON dict in source_description | TTL/OWL source → Pydantic + entity_types + edge_type_map | Single definition powers all constraints |
| Ontology storage | Supabase only | TTL (source) + Supabase (runtime) + Graphiti (extraction) | Three representations from one source |
| Ingestion trigger | Cortex Agent inline | SQS queue → Lambda | Decoupled, supports backfill, retry |
| Backfill | Not addressed | First-class pipeline using same SQS/Lambda | Graph useful day 1 only with historical data |
| GraphEngine interface | Custom Protocol abstraction | Graphiti API directly | Simpler, no current swap risk |
| Week 1 deliverable | Ontology + recipes | Ontology + backfill + queryable graph | Prove graph value before building intelligence |

**V2 additions from production data validation (2026-05-03):**
- Skill source priority reversed: `round.skills[]` is primary, `requisition.must_have_skills[]` is sparse supplement
- Candidate→Skill is episodic-only; structured path is Candidate→Competency
- Three new episodic sources: scorecard_transcript, recall_bots.transcript_data, intake_transcript
- CompanyEntity and TeamEntity confirmed episodic-only (zero structured fields)
- Capacity validated: ~1,800 nodes + ~6,400 edges at current production volumes

**V2.1 additions from deep data audit (2026-05-03):**
- **Two new entity types:** LocationEntity (triplet from `requisitions.role_location`), TraitEntity (episodic from question_summaries/transcripts)
- **Five new edge types:** WITHDREW_FROM, LOCATED_IN, BASED_IN, EXHIBITS, DEFAULT_FOR
- **Three new event types:** `candidate_withdrawn` (triplet), `jd_available` (episodic), `question_summaries_available` (episodic)
- **Competency resolution strategy:** 787→~200-300 canonical competencies via embedding clustering + LLM verification before backfill
- **Round category normalization:** 16 production variants → 9 canonical values (lowercase, spelling unification)
- **Requisition enrichment:** `experience_min_years`, `experience_max_years`, `role_location` now in triplet path (all 115 reqs populated)
- **Interviewer panel structure:** `rounds.default_interviewer_emails` → DEFAULT_FOR edges
- **Interview guidelines:** `rounds.guidelines` stored in Round node attributes for future coaching signal
- **Candidate withdrawal:** Separate WITHDREW_FROM edge (8 production cases, distinct from REJECTED_BY)
- **Candidate identity model:** Two-layer — name visible at org level for actionability, stripped to hashed ref for cross-org benchmarks
- **Parked for later:** Assessment evaluations (assessment_evaluations, assessment_instances), debrief_ai_summary cross-candidate rankings

Everything else unchanged from V1: intelligence tables, recipes, OODA loop, compliance, cost triggers, product surfaces, moat thesis.

---

## Migration Strategy (If Needed)

The ontology is a **write-time constraint**, not a runtime schema. Neo4j is schema-less — existing graph data remains valid regardless of ontology changes.

### Adding to the Ontology (new entity types, relationships, or fields)

| Change | What to do | Data migration? |
|--------|-----------|----------------|
| New entity type (e.g., `CertificationEntity`) | Add Pydantic model to `entity_types.py`, edges to `edge_type_map.py`, class to `recruitment.ttl`. Redeploy. | None for the deploy itself — existing graph untouched. Replaying historical text to surface the new type is a **separate backfill operation** with its own safeguards (see *Historical Re-ingestion* below). Do not couple it to the deploy. |
| New relationship (e.g., `MENTORS`) | Add to `edge_type_map.py` + `recruitment.ttl`. Redeploy. | None. |
| New optional field on existing type | Update Pydantic model. Redeploy. | None. Old nodes simply lack the property — Neo4j doesn't care. |
| Expand a Literal enum | Update Pydantic model. Redeploy. | None. |

### Changing the Ontology (renames, removals, restructuring)

| Change | What to do | Data migration? |
|--------|-----------|----------------|
| Rename entity type (`RolePattern` → `Archetype`) | 1. Run Cypher: `MATCH (n:RolePattern) SET n:Archetype REMOVE n:RolePattern` **before** code deploy. 2. Update all three ontology files. 3. Redeploy. | Yes — Cypher migration first, then code. Deploying code before migration creates duplicates. |
| Rename relationship (`STRONG_IN` → `EXCELS_AT`) | 1. Run Cypher: recreate edges with new type (Neo4j can't rename in-place). 2. Update ontology files. 3. Redeploy. | Yes — Cypher migration first. |
| Remove entity type | Remove from `entity_types.py` + `edge_type_map.py`. Redeploy. Optionally clean up: `MATCH (n:ObsoleteType) DETACH DELETE n`. | Optional cleanup. Orphaned nodes don't interfere with new ingestion. |
| Remove field from entity | Remove from Pydantic model. Redeploy. Old nodes retain the property harmlessly. Optionally: `MATCH (n:Type) REMOVE n.old_field`. | Optional cleanup. |

### Key Principle

**Additive changes are free. Renames require Cypher migration before deploy. Removals are optional cleanup.** Historical re-ingestion (replaying old text against an updated ontology) is a **separate, guarded operation** — never bundled with a deploy. It relies on Graphiti's entity resolution merging into existing nodes, and that assumption must be validated per change. See below.

### Historical Re-ingestion (Backfill)

Re-ingesting historical text after an ontology change can surface entities or relationships that were missed at original write time. It can also create duplicates or stray nodes if entity-resolution keys aren't aligned with the change. Treat every backfill as a migration, not a refresh.

**Preconditions (do not skip):**

1. **Define the merge contract.** For each affected entity type, record the resolution keys Graphiti will use (e.g., normalized name + org scope). If the change altered any field that participates in resolution, freeze the contract first or expect duplicates.
2. **Identify uniqueness invariants.** For each `(type, key)` and each relationship `(src, edge, dst)`, record the expected pre-backfill count. These are your before-numbers.
3. **Have an undo path.** Either (a) tag every node/edge created during the backfill with a `backfill_run_id` property so it can be deleted with one Cypher statement, or (b) take a Neo4j snapshot/dump before starting. No backfill without one of the two.

**Required procedure:**

1. **Stage first.** Run the backfill end-to-end on a Neo4j staging instance restored from a recent prod dump. Production replay is gated on staging passing checks 4–5 below.
2. **Bound the scope.** Replay a small, representative slice (e.g., one org, one month) before full replay. Compare metrics against expectations.
3. **Tag the run.** Stamp every node/edge written by the backfill with `backfill_run_id` and `backfill_started_at` so the work is attributable and reversible.
4. **Validate dedupe.** After the slice, compare counts: total nodes per type, total edges per relationship, and `(type, resolution_key)` duplicates. New duplicates above an agreed threshold (e.g., > 0.5% growth in `(type, key)` collisions) **fails the backfill** — stop, do not proceed to full replay.
5. **Validate semantics.** Spot-check 20+ resolved entities: were they merged into the right pre-existing nodes, or did Graphiti create parallel nodes? Parallel-node creation fails the backfill.
6. **Promote.** Only after staging passes 4–5, run on production with the same tagging and the same post-run validation.

**Rollback:**

If post-run validation fails (or duplicates are discovered later), delete the run with `MATCH (n {backfill_run_id: $id}) DETACH DELETE n` and `MATCH ()-[r {backfill_run_id: $id}]-() DELETE r`, or restore from the pre-backfill snapshot. Do not attempt manual fix-up unless the duplicate set is provably bounded.

**Never:**

- Run historical re-ingestion in the same deploy that introduced the ontology change.
- Run it without `backfill_run_id` tagging or a snapshot.
- Skip the staged slice "because the change looked additive" — additive at the schema level can still break resolution.

---

## References

- **V1 Cortex Design:** `docs/superpowers/specs/2026-04-13-cortex-design.md`
- **GoingMeta Repository:** https://github.com/jbarrasa/goingmeta (sessions 28-32, 39, 45)
- **Neo4j NLP + Ontology Guide:** https://neo4j.com/labs/apoc/5/nlp/build-knowledge-graph-nlp-ontologies/
- **Graphiti Library:** https://github.com/getzep/graphiti
- **Cortex Demo App (V1 UI):** `openrecruiting-ai-v2` (separate repo)
- **O*NET Skills Taxonomy:** https://www.onetonline.org/ (seed data for base ontology)
