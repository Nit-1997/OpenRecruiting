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
 *
 * TWO BUDGETS, because a wall-clock micro-benchmark cannot gate a shared
 * runner. That claim above went untested until CI started running tests at
 * all; the first real run measured 90.45 µs on the offset-suffix leg against
 * its 60 µs budget and 82.76 against 70, on the very commit that had just
 * passed on a quieter runner. The noise floor on a contended 2-core box is
 * unbounded — a noisy neighbour sets it, not this code — so no single
 * threshold is both tight enough to catch a regression and loose enough never
 * to flake, and a gate that cries wolf trains everyone to ignore it.
 *
 * So CI enforces a CATASTROPHIC-regression ceiling instead of a tuning budget.
 * The bug this file exists to catch — `new Intl.DateTimeFormat(...)` per call,
 * the 4-second render — costs roughly 16,000 µs/call. CI_SLACK of 10 puts the
 * slowest leg's ceiling at 600 µs: ~6× above the worst contention yet measured,
 * and ~25× below the regression it is looking for. Both margins are wide.
 * Local runs keep the tight budgets, where the numbers mean something.
 */

import { describe, expect, test } from 'bun:test';
import {
  formatScheduledDate,
  formatScheduledDateTime,
  formatScheduledTime,
} from '@/lib/format-scheduled';

// GitHub Actions sets CI=true; so does essentially every other runner.
const IS_CI = process.env.CI === 'true' || process.env.CI === '1';

/** Tight locally, catastrophic-regression ceiling on a shared runner. */
function budget(usPerCall: number): number {
  return IS_CI ? usPerCall * 10 : usPerCall;
}

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
    expect(usPerCall).toBeLessThan(budget(50));
  });

  test('formatScheduledTime stays under 60 µs/call (offset suffix is the slowest leg)', () => {
    const iso = '2026-05-21T19:00:00+00:00';
    const usPerCall = bench('formatScheduledTime(saved tz, offset)', 1000, () => {
      formatScheduledTime(iso, 'America/New_York');
    });
    expect(usPerCall).toBeLessThan(budget(60));
  });

  test('formatScheduledDateTime stays under 70 µs/call (combined render)', () => {
    const iso = '2026-05-21T19:00:00+00:00';
    const usPerCall = bench('formatScheduledDateTime(saved tz, offset)', 1000, () => {
      formatScheduledDateTime(iso, 'America/New_York');
    });
    expect(usPerCall).toBeLessThan(budget(70));
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
    expect(usPerCall).toBeLessThan(budget(50));
  });

  test('handles null inputs without throwing or wasting time', () => {
    const usPerCall = bench('formatScheduledDate(null)', 5_000, () => {
      formatScheduledDate(null, 'America/New_York');
    });
    // Null path is a single string comparison — should be cheap.
    expect(usPerCall).toBeLessThan(budget(5));
  });
});
