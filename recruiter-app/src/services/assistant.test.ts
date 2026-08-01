import { afterEach, describe, expect, mock, test } from 'bun:test';
import { classifyAssistantIntent } from './assistant';

const originalFetch = globalThis.fetch;

describe('classifyAssistantIntent', () => {
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test('returns the backend intent', async () => {
    globalThis.fetch = mock(
      async () =>
        new Response(JSON.stringify({ intent: 'browse_roles' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    ) as unknown as typeof fetch;
    expect(await classifyAssistantIntent('show me roles')).toBe('browse_roles');
  });

  test('fails open to out_of_scope on a network error', async () => {
    globalThis.fetch = mock(async () => {
      throw new Error('network down');
    }) as unknown as typeof fetch;
    expect(await classifyAssistantIntent('???')).toBe('out_of_scope');
  });
});
