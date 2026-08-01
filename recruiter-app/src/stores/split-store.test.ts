import { beforeEach, describe, expect, test } from 'bun:test';
import { useSplitStore } from './split-store';

describe('useSplitStore', () => {
  beforeEach(() => {
    localStorage.clear();
    useSplitStore.getState().reset();
  });

  test('default ratio is 0.55', () => {
    expect(useSplitStore.getState().ratio).toBeCloseTo(0.55, 5);
  });

  test('setRatio clamps below 0.32', () => {
    useSplitStore.getState().setRatio(0.1);
    expect(useSplitStore.getState().ratio).toBeCloseTo(0.32, 5);
  });

  test('setRatio clamps above 0.72', () => {
    useSplitStore.getState().setRatio(0.9);
    expect(useSplitStore.getState().ratio).toBeCloseTo(0.72, 5);
  });

  test('setRatio persists within clamp', () => {
    useSplitStore.getState().setRatio(0.6);
    expect(useSplitStore.getState().ratio).toBeCloseTo(0.6, 5);
  });

  test('persists to localStorage under key openrecruiting.split.v1', () => {
    useSplitStore.getState().setRatio(0.5);
    const raw = localStorage.getItem('openrecruiting.split.v1');
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw ?? '{}').state.ratio).toBeCloseTo(0.5, 5);
  });

  test('setRatio falls back to default on NaN', () => {
    useSplitStore.getState().setRatio(Number.NaN);
    expect(useSplitStore.getState().ratio).toBeCloseTo(0.55, 5);
  });
});
