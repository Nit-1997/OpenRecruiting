/**
 * Unit tests for the shared relative-time helper. This is the de-duped source
 * of the "Xm/Xh/Xd ago" formatting used across the debrief surfaces (packet
 * toolbar, role tab, insight summary) — the same helper that replaced the raw
 * ISO timestamp leaking into the debrief insight summary.
 */

import { describe, expect, test } from 'bun:test';
import { relativeTimeFrom } from './relative-time';

const ISO_PATTERN = /\d{4}-\d{2}-\d{2}T/;

describe('relativeTimeFrom', () => {
  test('renders minutes for a recent timestamp (never a raw ISO string)', () => {
    const twoMinAgo = new Date(Date.now() - 2 * 60_000).toISOString();
    const out = relativeTimeFrom(twoMinAgo);
    expect(out).toBe('2m ago');
    expect(out).not.toMatch(ISO_PATTERN);
  });

  test('clamps a just-now timestamp to "1m ago" (no "0m ago")', () => {
    expect(relativeTimeFrom(new Date().toISOString())).toBe('1m ago');
  });

  test('renders hours past the 60-minute boundary', () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60_000).toISOString();
    expect(relativeTimeFrom(threeHoursAgo)).toBe('3h ago');
  });

  test('renders days past the 24-hour boundary', () => {
    const fiveDaysAgo = new Date(Date.now() - 5 * 24 * 60 * 60_000).toISOString();
    expect(relativeTimeFrom(fiveDaysAgo)).toBe('5d ago');
  });
});
