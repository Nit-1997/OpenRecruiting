import { describe, expect, it } from 'bun:test';
import { isRoundScreenable } from './screening-eligibility';

describe('isRoundScreenable', () => {
  it('R1 "Recruiter Screen" / culture at index 0 → true (name match)', () => {
    expect(isRoundScreenable('Recruiter Screen', 'culture', 0)).toBe(true);
  });

  it('R3 "Hiring Manager Behavioral" / behavioral at index 2 → false (not first, no name match)', () => {
    expect(isRoundScreenable('Hiring Manager Behavioral', 'behavioral', 2)).toBe(false);
  });

  it('R2 design at index 1 → false (exercise category)', () => {
    expect(isRoundScreenable('System Design', 'design', 1)).toBe(false);
  });

  it('"Recruiter Phone Screen" is screenable at any index (name match)', () => {
    expect(isRoundScreenable('Recruiter Phone Screen', 'behavioral', 3)).toBe(true);
    expect(isRoundScreenable('Recruiter Phone Screen', 'design', 5)).toBe(true);
  });

  it('first-round conversational category is screenable even without a screen name', () => {
    expect(isRoundScreenable('Culture Fit', 'culture', 0)).toBe(true);
    expect(isRoundScreenable('Motivation', 'motivation', 0)).toBe(true);
  });

  it('first-round exercise category is NOT screenable', () => {
    expect(isRoundScreenable('Live Coding', 'coding', 0)).toBe(false);
    expect(isRoundScreenable('Take Home Review', 'take_home', 0)).toBe(false);
  });

  it('category "screening" or "recruiter" is screenable by category alone', () => {
    expect(isRoundScreenable('Anything', 'screening', 4)).toBe(true);
    expect(isRoundScreenable('Anything', 'recruiter', 4)).toBe(true);
  });

  it('bare word "screen" as a token matches, "Screenwriter" does not', () => {
    expect(isRoundScreenable('Final Screen', 'panel', 2)).toBe(true);
    expect(isRoundScreenable('Screenwriter Panel', 'panel', 2)).toBe(false);
  });

  it('empty/blank inputs → false', () => {
    expect(isRoundScreenable('', '', 0)).toBe(false);
    expect(isRoundScreenable(null, null, 0)).toBe(false);
    expect(isRoundScreenable(undefined, undefined, 0)).toBe(false);
  });
});
