import { afterEach, describe, expect, mock, test } from 'bun:test';
import {
  attachScreening,
  derivePersona,
  detachScreening,
  generateScreening,
  getPersona,
  getScreening,
  getScreeningSuggestion,
  inviteCandidateRound,
  inviteScreening,
  type ScreeningConfig,
  savePersona,
  saveScreening,
} from './screening';

const originalFetch = globalThis.fetch;

interface CapturedCall {
  url: string;
  method: string;
  body: unknown;
}

// Install a fetch mock that records the last request and returns `responseBody`
// (or an empty 204). Returns the capture ref the test asserts against.
function captureFetch(responseBody: unknown, status = 200): CapturedCall {
  const captured: CapturedCall = { url: '', method: '', body: undefined };
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    captured.url = typeof input === 'string' ? input : input.toString();
    captured.method = init?.method ?? 'GET';
    captured.body = init?.body ? JSON.parse(init.body as string) : undefined;
    if (responseBody === undefined) {
      return new Response(null, { status: 204 });
    }
    return new Response(JSON.stringify(responseBody), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  }) as unknown as typeof fetch;
  return captured;
}

function sampleSnakeConfig() {
  return {
    round_id: 'rnd-1',
    enabled: true,
    voice: 'Aura · "Luna"',
    follow_up_style: 'adaptive',
    est_duration_minutes: 18,
    validity_days: 14,
    deploy_scope: 'all_resume_passed',
    questions: [
      {
        id: 'q1',
        order_index: 0,
        title: 'Metric ownership',
        prompt: 'Walk me through a metric you owned.',
        probe: 'Was the lift causal?',
        signal: 'Execution',
        dimension: 'Ownership',
        duration_minutes: 5,
      },
    ],
  };
}

function sampleCamelConfig(): ScreeningConfig {
  return {
    roundId: 'rnd-1',
    enabled: true,
    voice: 'Aura · "Luna"',
    followUpStyle: 'adaptive',
    estDurationMinutes: 18,
    validityDays: 14,
    deployScope: 'all_resume_passed',
    questions: [
      {
        id: 'q1',
        orderIndex: 0,
        title: 'Metric ownership',
        prompt: 'Walk me through a metric you owned.',
        probe: 'Was the lift causal?',
        signal: 'Execution',
        dimension: 'Ownership',
        durationMinutes: 5,
      },
    ],
  };
}

describe('screening service', () => {
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test('saveScreening PUTs the camel→snake config to the screening path', async () => {
    const captured = captureFetch(sampleSnakeConfig());
    const result = await saveScreening('req-9', 'rnd-1', sampleCamelConfig());

    expect(captured.method).toBe('PUT');
    expect(captured.url).toContain('/api/v2/roles/req-9/rounds/rnd-1/screening');
    // Body must be snake_case for the backend.
    const body = captured.body as Record<string, unknown>;
    expect(body.round_id).toBe('rnd-1');
    expect(body.follow_up_style).toBe('adaptive');
    expect(body.est_duration_minutes).toBe(18);
    expect(body.deploy_scope).toBe('all_resume_passed');
    const q = (body.questions as Array<Record<string, unknown>>)[0];
    expect(q?.order_index).toBe(0);
    expect(q?.duration_minutes).toBe(5);
    // Response is mapped back to camelCase.
    expect(result.followUpStyle).toBe('adaptive');
    expect(result.questions[0]?.orderIndex).toBe(0);
    expect(result.questions[0]?.durationMinutes).toBe(5);
  });

  test('generateScreening POSTs to the generate path with preferences', async () => {
    const captured = captureFetch(sampleSnakeConfig());
    const result = await generateScreening('req-9', 'rnd-1', {
      preferences: 'go deep on PLG',
    });

    expect(captured.method).toBe('POST');
    expect(captured.url).toContain('/api/v2/roles/req-9/rounds/rnd-1/screening/generate');
    expect((captured.body as Record<string, unknown>).preferences).toBe('go deep on PLG');
    expect(result.roundId).toBe('rnd-1');
    expect(result.questions).toHaveLength(1);
  });

  test('getScreening GETs the screening path and maps null', async () => {
    const captured = captureFetch(null);
    const result = await getScreening('req-9', 'rnd-1');
    expect(captured.method).toBe('GET');
    expect(captured.url).toContain('/api/v2/roles/req-9/rounds/rnd-1/screening');
    expect(result).toBeNull();
  });

  test('attachScreening POSTs to the attach path and maps the response', async () => {
    const captured = captureFetch(sampleSnakeConfig());
    const result = await attachScreening('req-9', 'rnd-1');
    expect(captured.method).toBe('POST');
    expect(captured.url).toContain('/api/v2/roles/req-9/rounds/rnd-1/screening/attach');
    expect(result.enabled).toBe(true);
  });

  test('detachScreening POSTs to the detach path', async () => {
    const captured = captureFetch({ ...sampleSnakeConfig(), enabled: false });
    const result = await detachScreening('req-9', 'rnd-1');
    expect(captured.method).toBe('POST');
    expect(captured.url).toContain('/api/v2/roles/req-9/rounds/rnd-1/screening/detach');
    expect(result.enabled).toBe(false);
  });

  test('attachScreening on a null response throws a CLEAR error (not a round_id TypeError)', async () => {
    // Defense in depth: configFromWire must never surface the cryptic
    // "Cannot read properties of null (reading 'round_id')" TypeError.
    captureFetch(null);
    let caught: unknown;
    try {
      await attachScreening('req-9', 'rnd-1');
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(Error);
    const message = (caught as Error).message;
    expect(message).toContain('No screening config returned');
    expect(message).not.toContain('round_id');
  });

  test('saveScreening on a null response throws a CLEAR error (not a round_id TypeError)', async () => {
    captureFetch(null);
    let caught: unknown;
    try {
      await saveScreening('req-9', 'rnd-1', sampleCamelConfig());
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toContain('No screening config returned');
  });

  test('inviteScreening POSTs emails + scope to the invite path', async () => {
    const captured = captureFetch({ invited: 3 });
    await inviteScreening('req-9', 'rnd-1', {
      emails: ['a@x.com', 'b@x.com'],
      scope: 'all_resume_passed',
    });
    expect(captured.method).toBe('POST');
    expect(captured.url).toContain('/api/v2/roles/req-9/rounds/rnd-1/screening/invite');
    const body = captured.body as Record<string, unknown>;
    expect(body.emails).toEqual(['a@x.com', 'b@x.com']);
    expect(body.scope).toBe('all_resume_passed');
  });

  test('inviteCandidateRound POSTs to the candidate-round path and maps snake→camel', async () => {
    const captured = captureFetch({
      token: 'tok-cr',
      expires_at: '2030-01-01T00:00:00+00:00',
      verify_url: 'http://localhost:3005/screening/tok-cr/verify',
      validity_days: 11,
    });
    const result = await inviteCandidateRound('cr-42');

    expect(captured.method).toBe('POST');
    expect(captured.url).toContain('/api/v2/screening/candidate-rounds/cr-42/invite');
    expect(result.token).toBe('tok-cr');
    expect(result.expiresAt).toBe('2030-01-01T00:00:00+00:00');
    expect(result.verifyUrl).toBe('http://localhost:3005/screening/tok-cr/verify');
    expect(result.validityDays).toBe(11);
  });
});

function samplePersonaWire() {
  return {
    persona_id: 'persona-1',
    composed_text: 'Warm but probing.',
    dimensions: [
      { key: 'tone_rapport', value: 'Warm, conversational', confidence: 0.82, source: 'cortex' },
      { key: 'structure', value: 'Two probes per topic', confidence: 0.3, source: 'generic' },
    ],
  };
}

describe('screening persona service', () => {
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test('derivePersona POSTs to the persona/derive path and maps to camel', async () => {
    const captured = captureFetch(samplePersonaWire());
    const result = await derivePersona('req-9', 'rnd-1');

    expect(captured.method).toBe('POST');
    expect(captured.url).toContain('/api/v2/roles/req-9/rounds/rnd-1/screening/persona/derive');
    expect(result.personaId).toBe('persona-1');
    expect(result.composedText).toBe('Warm but probing.');
    expect(result.dimensions[0]?.key).toBe('tone_rapport');
    expect(result.dimensions[0]?.confidence).toBe(0.82);
    expect(result.dimensions[0]?.source).toBe('cortex');
  });

  test('getPersona GETs the persona path and maps the empty shape', async () => {
    const captured = captureFetch({ persona_id: null, dimensions: [], composed_text: '' });
    const result = await getPersona('req-9', 'rnd-1');

    expect(captured.method).toBe('GET');
    expect(captured.url).toContain('/api/v2/roles/req-9/rounds/rnd-1/screening/persona');
    expect(result.personaId).toBeNull();
    expect(result.dimensions).toHaveLength(0);
    expect(result.composedText).toBe('');
  });

  test('savePersona PUTs {dimensions} to the persona path and maps the response', async () => {
    const captured = captureFetch(samplePersonaWire());
    const result = await savePersona('req-9', 'rnd-1', {
      dimensions: [
        {
          key: 'tone_rapport',
          value: 'Warm, conversational',
          confidence: 0.82,
          source: 'recruiter',
        },
      ],
    });

    expect(captured.method).toBe('PUT');
    expect(captured.url).toContain('/api/v2/roles/req-9/rounds/rnd-1/screening/persona');
    expect(captured.url).not.toContain('/derive');
    const body = captured.body as Record<string, unknown>;
    const dims = body.dimensions as Array<Record<string, unknown>>;
    expect(dims[0]?.key).toBe('tone_rapport');
    expect(dims[0]?.value).toBe('Warm, conversational');
    expect(dims[0]?.source).toBe('recruiter');
    expect(dims[0]?.confidence).toBe(0.82);
    // Response mapped back to camel.
    expect(result.personaId).toBe('persona-1');
    expect(result.dimensions[0]?.key).toBe('tone_rapport');
  });

  test('getScreeningSuggestion GETs the role suggestion path and maps snake→camel', async () => {
    const captured = captureFetch({
      should_suggest: true,
      reason: '3 candidates were repeatedly weak in System Design.',
      target_round_id: 'rnd-1',
    });
    const result = await getScreeningSuggestion('req-9');

    expect(captured.method).toBe('GET');
    expect(captured.url).toContain('/api/v2/roles/req-9/screening/suggestion');
    expect(result.shouldSuggest).toBe(true);
    expect(result.reason).toContain('System Design');
    expect(result.targetRoundId).toBe('rnd-1');
  });

  test('getScreeningSuggestion maps a no-suggestion response', async () => {
    captureFetch({ should_suggest: false, reason: '', target_round_id: null });
    const result = await getScreeningSuggestion('req-9');
    expect(result.shouldSuggest).toBe(false);
    expect(result.targetRoundId).toBeNull();
  });
});
