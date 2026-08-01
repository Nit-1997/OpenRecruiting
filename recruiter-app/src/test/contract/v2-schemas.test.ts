/**
 * Contract tests: v2 backend Pydantic schemas vs v2 frontend domain types.
 *
 * Drift alarm. If the BE makes a field required, removes one, or changes
 * an enum, these tests fail with a precise diff — that's what prevented
 * the interviewer_email-required-vs-optional drift from shipping again.
 *
 * Generation: run `python3 backend/scripts/export_v2_schemas.py`
 * to regenerate `v2-schemas.generated.json` from the live Pydantic models.
 *
 * The test reads that file (real BE) and asserts that the documented FE
 * contract (the SHAPES below, which mirror src/domain/) matches. We
 * deliberately don't `import { ScheduleInterviewInput } from '@/domain'`
 * — TypeScript types are erased at runtime, so we have to encode the
 * expected shape declaratively here.
 */

import { describe, expect, test } from 'bun:test';
import generated from './v2-schemas.generated.json';

type JsonSchema = {
  type?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  anyOf?: JsonSchema[];
  $ref?: string;
  default?: unknown;
  enum?: string[];
  format?: string;
};

type GeneratedSchemas = Record<string, JsonSchema>;

const SCHEMAS = generated as GeneratedSchemas;

function getSchema(name: string): JsonSchema {
  const s = SCHEMAS[name];
  if (!s) throw new Error(`Schema ${name} not found in generated file`);
  return s;
}

/**
 * Pydantic emits `Optional[T]` as `anyOf: [{type:T}, {type:null}]` with a
 * `default: null`. A field is required iff it appears in the schema's
 * top-level `required: []` array. This helper collapses both signals into
 * a single ergonomic check.
 */
function isRequired(schema: JsonSchema, field: string): boolean {
  return (schema.required ?? []).includes(field);
}

function hasProperty(schema: JsonSchema, field: string): boolean {
  return field in (schema.properties ?? {});
}

// ============================================================================
// Journey schemas
// ============================================================================

describe('contract: ScheduleInterviewRequest', () => {
  const schema = getSchema('ScheduleInterviewRequest');

  test('exposes the v1-parity field set', () => {
    expect(hasProperty(schema, 'scheduled_at')).toBe(true);
    expect(hasProperty(schema, 'interviewer_email')).toBe(true);
    expect(hasProperty(schema, 'interviewer_name')).toBe(true);
    expect(hasProperty(schema, 'meeting_url')).toBe(true);
    expect(hasProperty(schema, 'scheduling_timezone')).toBe(true);
  });

  test('scheduled_at is the only required field', () => {
    // This is the v1 contract we restored — interviewer_email used to be
    // required (Pydantic EmailStr no default), which silently broke v2's
    // FE which submitted with empty email when the recruiter didn't have
    // one yet. If this fails: someone made a field required at the BE
    // and the FE will start dropping rounds.
    expect(isRequired(schema, 'scheduled_at')).toBe(true);
    expect(isRequired(schema, 'interviewer_email')).toBe(false);
    expect(isRequired(schema, 'interviewer_name')).toBe(false);
    expect(isRequired(schema, 'meeting_url')).toBe(false);
    expect(isRequired(schema, 'scheduling_timezone')).toBe(false);
  });

  test('scheduled_at is typed as a date-time string (so naive ISO without offset is rejected at the FE boundary)', () => {
    const f = schema.properties?.scheduled_at;
    // Pydantic emits date-time format for `datetime`.
    expect(f?.format).toBe('date-time');
  });

  test('rejects unknown extra fields surface in the schema', () => {
    // Pydantic v2 defaults to extra='ignore'. If we ever flip to
    // extra='forbid' the BE will start 422-ing on legacy clients — this
    // is the early-warning test for that.
    // (No additionalProperties means default 'ignore'; presence of
    // additionalProperties: false would mean 'forbid'.)
    const additional = (schema as { additionalProperties?: unknown }).additionalProperties;
    expect(additional === undefined || additional === true).toBe(true);
  });
});

describe('contract: RescheduleInterviewRequest', () => {
  const schema = getSchema('RescheduleInterviewRequest');

  test('all fields are optional (partial update semantics)', () => {
    // Reschedule is a PATCH-style endpoint — sending only the changed
    // fields is the documented behaviour. If a field becomes required,
    // every existing FE call site that omits it will start 422-ing.
    expect(schema.required ?? []).toEqual([]);
  });

  test('exposes clear_meeting_url toggle for explicit URL removal', () => {
    expect(hasProperty(schema, 'clear_meeting_url')).toBe(true);
  });
});

// ============================================================================
// Feedback schemas
// ============================================================================

describe('contract: SubmitFeedbackRequest', () => {
  const schema = getSchema('SubmitFeedbackRequest');

  test('requires entries + rating + summary; everything else is optional', () => {
    expect(isRequired(schema, 'entries')).toBe(true);
    expect(isRequired(schema, 'rating')).toBe(true);
    expect(isRequired(schema, 'summary')).toBe(true);
    // scorecard is the forward-compat field — accepted but not required.
    expect(isRequired(schema, 'scorecard')).toBe(false);
  });

  test('entries is an array (FE must wrap a single feedback in a list)', () => {
    expect(schema.properties?.entries?.type).toBe('array');
  });
});

describe('contract: RequestFeedbackRequest', () => {
  const schema = getSchema('RequestFeedbackRequest');

  test('interviewer_email is required (cannot send a notification without an address)', () => {
    expect(isRequired(schema, 'interviewer_email')).toBe(true);
  });

  test('channel is a Literal enum of email|slack|both', () => {
    // Pydantic emits `Literal[...]` as enum on the property.
    const channel = schema.properties?.channel;
    expect(channel).toBeDefined();
    expect(channel?.enum ?? []).toEqual(expect.arrayContaining(['email', 'slack', 'both']));
  });
});

describe('contract: ReprocessRequest', () => {
  const schema = getSchema('ReprocessRequest');

  test('force is a boolean (must not be a string)', () => {
    expect(schema.properties?.force?.type).toBe('boolean');
  });

  test('force defaults to false (no accidental skip_prereq_check)', () => {
    // Defaulting to true would bypass the in-flight guard at
    // feedback_job_service.py:46-47 (see CLAUDE.md May 2026 incident).
    expect(schema.properties?.force?.default).toBe(false);
  });
});

// ============================================================================
// Plan schemas
// ============================================================================

describe('contract: AddRoundRequest', () => {
  const schema = getSchema('AddRoundRequest');

  test('name is required; duration_minutes defaults to 45', () => {
    expect(isRequired(schema, 'name')).toBe(true);
    expect(schema.properties?.duration_minutes?.default).toBe(45);
  });
});

describe('contract: UpdateRoundRequest', () => {
  const schema = getSchema('UpdateRoundRequest');

  test('all fields optional (PATCH-style)', () => {
    expect(schema.required ?? []).toEqual([]);
  });
});

describe('contract: ReorderRoundItem', () => {
  const schema = getSchema('ReorderRoundItem');

  test('requires round_id (uuid) + round_number (int)', () => {
    expect(isRequired(schema, 'round_id')).toBe(true);
    expect(isRequired(schema, 'round_number')).toBe(true);
    expect(schema.properties?.round_id?.format).toBe('uuid');
  });
});

describe('contract: AddQuestionRequest / UpdateQuestionRequest', () => {
  test('AddQuestionRequest requires heading; description optional', () => {
    const s = getSchema('AddQuestionRequest');
    expect(isRequired(s, 'heading')).toBe(true);
    expect(isRequired(s, 'description')).toBe(false);
  });

  test('UpdateQuestionRequest is fully optional (PATCH-style)', () => {
    const s = getSchema('UpdateQuestionRequest');
    expect(s.required ?? []).toEqual([]);
  });
});

// ============================================================================
// FE→BE shape compatibility
// ============================================================================

describe('contract: FE payload shapes match BE schemas', () => {
  /**
   * What this test pins: every field the FE ScheduleInterviewInput type
   * lists is also a property in the BE schema. If the FE adds a field
   * the BE doesn't know, we'd silently strip it server-side (extra=ignore)
   * — this surfaces the gap.
   */
  test('FE ScheduleInterviewInput field names ⊆ BE properties', () => {
    const FE_FIELDS = [
      'scheduled_at',
      'interviewer_email',
      'interviewer_name',
      'meeting_url',
      'scheduling_timezone',
    ];
    const schema = getSchema('ScheduleInterviewRequest');
    const beFields = Object.keys(schema.properties ?? {});
    for (const f of FE_FIELDS) {
      expect(beFields).toContain(f);
    }
  });

  test('FE SubmitFeedbackInput shape includes entries + rating + summary', () => {
    const FE_FIELDS = ['entries', 'rating', 'summary'];
    const schema = getSchema('SubmitFeedbackRequest');
    const beFields = Object.keys(schema.properties ?? {});
    for (const f of FE_FIELDS) {
      expect(beFields).toContain(f);
    }
  });

  test('FE AddRoundInput shape matches BE AddRoundRequest', () => {
    const FE_FIELDS = ['name', 'category', 'duration_minutes', 'description'];
    const schema = getSchema('AddRoundRequest');
    const beFields = Object.keys(schema.properties ?? {});
    for (const f of FE_FIELDS) {
      expect(beFields).toContain(f);
    }
  });
});
