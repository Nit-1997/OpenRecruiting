/**
 * Performance budget tests for the hottest formatter paths.
 *
 * `formatScheduledDate` runs once per pipeline cell, per re-render. A
 * 50-candidate pipeline with 5 rounds each = 250 calls per render — and
 * the cofounder hit a 4-second render once when this was implemented
 * with `new Intl.DateTimeFormat(...)` instantiated per call. We use the
 * cached helpers; pinning the per-call cost here so a regression
 * surfaces in CI rather than during a customer demo.
 *
 * Budgets are intentionally generous so flaky CI doesn't false-positive.
 * If the helper grows by 5× we still pass — that's about the level we
 * want to alarm at.
 */

import { describe, expect, test } from 'bun:test';
import {
  formatScheduledDate,
  formatScheduledDateTime,
  formatScheduledTime,
} from '@/lib/format-scheduled';

function bench(label: string, iterations: number, fn: () => void): number {
  // Warm the JIT — the first ~50 calls hit Intl.DateTimeFormat
  // initialisation and aren't representative.
  for (let i = 0; i < 50; i++) fn();
  const start = performance.now();
  for (let i = 0; i < iterations; i++) fn();
  const elapsed = performance.now() - start;
  const usPerCall = (elapsed / iterations) * 1000;
  // biome-ignore lint/suspicious/noConsole: bench output goes to test log
  console.log(`  ${label}: ${usPerCall.toFixed(2)} µs/call (${iterations} iters)`);
  return usPerCall;
}

describe('perf: format-scheduled', () => {
  test('formatScheduledDate stays under 50 µs/call at 1k iters', () => {
    const iso = '2026-05-21T19:00:00+00:00';
    const usPerCall = bench('formatScheduledDate(saved tz)', 1000, () => {
      formatScheduledDate(iso, 'America/New_York');
    });
    // Generous budget. Real number on M-series is ~5 µs.
    expect(usPerCall).toBeLessThan(50);
  });

  test('formatScheduledTime stays under 60 µs/call (offset suffix is the slowest leg)', () => {
    const iso = '2026-05-21T19:00:00+00:00';
    const usPerCall = bench('formatScheduledTime(saved tz, offset)', 1000, () => {
      formatScheduledTime(iso, 'America/New_York');
    });
    expect(usPerCall).toBeLessThan(60);
  });

  test('formatScheduledDateTime stays under 70 µs/call (combined render)', () => {
    const iso = '2026-05-21T19:00:00+00:00';
    const usPerCall = bench('formatScheduledDateTime(saved tz, offset)', 1000, () => {
      formatScheduledDateTime(iso, 'America/New_York');
    });
    expect(usPerCall).toBeLessThan(70);
  });

  test('repeated calls with the same tz get a stable per-call cost (cache locality)', () => {
    // A 50-candidate × 5-round pipeline calls the formatter 250× per
    // render. Real-world the calls are bunched on the same recruiter
    // tz, so this is the most representative micro-benchmark.
    const iso = '2026-05-21T19:00:00+00:00';
    const usPerCall = bench('formatScheduledDate(repeated same-tz, 5k iters)', 5_000, () => {
      formatScheduledDate(iso, 'America/New_York');
    });
    // 5k calls × 50 µs = 250 ms budget per render — well above what's
    // perceptible. If we drop into the ms-per-call range that means
    // something is allocating heavily in the hot path.
    expect(usPerCall).toBeLessThan(50);
  });

  test('handles null inputs without throwing or wasting time', () => {
    const usPerCall = bench('formatScheduledDate(null)', 5_000, () => {
      formatScheduledDate(null, 'America/New_York');
    });
    // Null path is a single string comparison — should be cheap.
    expect(usPerCall).toBeLessThan(5);
  });
});
