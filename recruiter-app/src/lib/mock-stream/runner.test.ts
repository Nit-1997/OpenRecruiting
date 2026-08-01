import { describe, expect, test } from 'bun:test';
import { createMockStream } from './runner';
import type { StreamScript } from './types';

describe('mock-stream runner', () => {
  test('yields events in order', async () => {
    const script: StreamScript = [
      { type: 'stage_start' },
      { type: 'prose_token', token: 'hi' },
      { type: 'stage_end', nextStage: 'next' },
    ];
    const received: string[] = [];
    for await (const ev of createMockStream(script, { speed: 0 })) {
      received.push(ev.type);
    }
    expect(received).toEqual(['stage_start', 'prose_token', 'stage_end']);
  });

  test('respects speed multiplier 0 for zero delay', async () => {
    const script: StreamScript = [{ type: 'prose_token', token: 'x' }];
    const t0 = Date.now();
    for await (const _ev of createMockStream(script, { speed: 0 })) {
      // consume
    }
    const elapsed = Date.now() - t0;
    expect(elapsed).toBeLessThan(20);
  });
});
