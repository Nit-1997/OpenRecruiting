import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { useThemeStore } from './theme-store';

beforeEach(() => {
  if (typeof localStorage !== 'undefined') localStorage.clear();
  useThemeStore.getState().setMode('light');
});

afterEach(() => {
  useThemeStore.getState().setMode('light');
});

describe('theme-store', () => {
  test('initial mode is light', () => {
    expect(useThemeStore.getState().mode).toBe('light');
  });

  test('toggle flips light to dark', () => {
    useThemeStore.getState().toggle();
    expect(useThemeStore.getState().mode).toBe('dark');
  });

  test('toggle flips dark back to light', () => {
    useThemeStore.getState().setMode('dark');
    useThemeStore.getState().toggle();
    expect(useThemeStore.getState().mode).toBe('light');
  });

  test('setMode sets the mode directly', () => {
    useThemeStore.getState().setMode('dark');
    expect(useThemeStore.getState().mode).toBe('dark');
  });

  test('apply is a no-op when document is absent but does not throw', () => {
    expect(() => useThemeStore.getState().apply()).not.toThrow();
  });

  test('toggling in dark DOM adds/removes the dark class', () => {
    if (typeof document === 'undefined') return;
    useThemeStore.getState().setMode('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    useThemeStore.getState().setMode('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });
});
