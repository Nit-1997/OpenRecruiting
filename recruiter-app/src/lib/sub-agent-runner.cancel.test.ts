import { describe, expect, test } from 'bun:test';
import { abortableDelay, beginRun, cancelRun } from './sub-agent-runner';

describe('sub-agent run cancellation', () => {
  test('beginRun returns a live (un-aborted) signal', () => {
    const signal = beginRun('brain');
    expect(signal.aborted).toBe(false);
    cancelRun('brain');
  });

  test('starting a new run for the same agent aborts the prior signal', () => {
    const first = beginRun('sourcing');
    const second = beginRun('sourcing');
    expect(first.aborted).toBe(true);
    expect(second.aborted).toBe(false);
    cancelRun('sourcing');
  });

  test('cancelRun aborts the live signal', () => {
    const signal = beginRun('debrief');
    expect(signal.aborted).toBe(false);
    cancelRun('debrief');
    expect(signal.aborted).toBe(true);
  });

  test('two different agents do not share a controller', () => {
    const sourcing = beginRun('sourcing');
    const brain = beginRun('brain');
    cancelRun('sourcing');
    expect(sourcing.aborted).toBe(true);
    expect(brain.aborted).toBe(false);
    cancelRun('brain');
  });

  test('abortableDelay resolves immediately when the signal is already aborted', async () => {
    const signal = beginRun('brain');
    cancelRun('brain');
    const started = Date.now();
    await abortableDelay(10_000, signal);
    // Must not wait the full 10s — already aborted, resolves on next tick.
    expect(Date.now() - started).toBeLessThan(500);
  });

  test('abortableDelay resolves early when aborted mid-wait', async () => {
    const signal = beginRun('debrief');
    const started = Date.now();
    const pending = abortableDelay(10_000, signal);
    cancelRun('debrief');
    await pending;
    expect(Date.now() - started).toBeLessThan(500);
  });

  test('abortableDelay waits the full duration when never aborted', async () => {
    const signal = beginRun('sourcing');
    const started = Date.now();
    await abortableDelay(30, signal);
    expect(Date.now() - started).toBeGreaterThanOrEqual(20);
    cancelRun('sourcing');
  });
});
