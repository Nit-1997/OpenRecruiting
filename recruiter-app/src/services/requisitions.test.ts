// Boundary-mapping coverage for the requisitions plan read.
//
// The v2 `/roles/{id}/plan` wire sends screening eligibility as
// `ai_screenable` / `ai_screenable_reason` (snake_case). The dashboard
// `@/domain` Round exposes them as camelCase `aiScreenable` /
// `aiScreenableReason` — this verifies the service maps that boundary.
//
// We mock `globalThis.fetch` (scoped + restored) rather than mock.module, per
// repo norms. test-setup.ts forces v2 OFF by default, so each test flips it on.

import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { getPlan } from './requisitions';

const originalFetch = globalThis.fetch;

function mockPlanResponse(rounds: unknown[]): void {
  globalThis.fetch = mock(
    async () =>
      new Response(JSON.stringify({ rounds }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
  ) as unknown as typeof fetch;
}

function wireRound(overrides: Record<string, unknown> = {}) {
  return {
    id: 'round-1',
    requisition_id: 'role-1',
    round_number: 1,
    name: 'Recruiter screen',
    category: 'screening',
    duration_minutes: 30,
    skills: [],
    guidelines: [],
    feedback_questions: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_V2_API = 'true';
});

afterEach(() => {
  process.env.NEXT_PUBLIC_V2_API = 'false';
  globalThis.fetch = originalFetch;
});

describe('requisitions.getPlan — screening eligibility mapping', () => {
  test('maps ai_screenable → aiScreenable and the reason', async () => {
    mockPlanResponse([
      wireRound({
        ai_screenable: true,
        ai_screenable_reason: 'Resume-passed candidates need a phone screen.',
      }),
    ]);

    const rounds = await getPlan('role-1');

    expect(rounds).toHaveLength(1);
    expect(rounds[0]?.aiScreenable).toBe(true);
    expect(rounds[0]?.aiScreenableReason).toBe('Resume-passed candidates need a phone screen.');
    // Snake-case wire fields must NOT leak onto the domain object.
    expect((rounds[0] as Record<string, unknown>).ai_screenable).toBeUndefined();
    expect((rounds[0] as Record<string, unknown>).ai_screenable_reason).toBeUndefined();
  });

  test('defaults aiScreenable to false when the round is not eligible', async () => {
    mockPlanResponse([wireRound({ ai_screenable: false })]);

    const rounds = await getPlan('role-1');

    expect(rounds[0]?.aiScreenable).toBe(false);
    expect(rounds[0]?.aiScreenableReason).toBeUndefined();
  });
});
