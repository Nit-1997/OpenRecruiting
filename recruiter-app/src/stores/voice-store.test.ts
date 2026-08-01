import { beforeEach, describe, expect, test } from 'bun:test';
import { useVoiceStore } from './voice-store';

beforeEach(() => {
  useVoiceStore.getState().end();
});

describe('voice-store', () => {
  test('initial state is inactive', () => {
    const s = useVoiceStore.getState();
    expect(s.active).toBe(false);
    expect(s.minimized).toBe(false);
    expect(s.seconds).toBe(0);
  });

  test('start sets active with owner tab', () => {
    useVoiceStore.getState().start('intake');
    const s = useVoiceStore.getState();
    expect(s.active).toBe(true);
    expect(s.ownerTabId).toBe('intake');
  });

  test('tick increments seconds only when active', () => {
    useVoiceStore.getState().tick();
    expect(useVoiceStore.getState().seconds).toBe(0);
    useVoiceStore.getState().start('intake');
    useVoiceStore.getState().tick();
    useVoiceStore.getState().tick();
    expect(useVoiceStore.getState().seconds).toBe(2);
  });

  test('minimize flips minimized flag', () => {
    useVoiceStore.getState().start('intake');
    useVoiceStore.getState().minimize();
    expect(useVoiceStore.getState().minimized).toBe(true);
    useVoiceStore.getState().minimize();
    expect(useVoiceStore.getState().minimized).toBe(false);
  });

  test('end resets everything', () => {
    useVoiceStore.getState().start('intake');
    useVoiceStore.getState().tick();
    useVoiceStore.getState().end();
    const s = useVoiceStore.getState();
    expect(s.active).toBe(false);
    expect(s.seconds).toBe(0);
    expect(s.ownerTabId).toBeNull();
  });

  test('addCaption appends to rolling list (max 5)', () => {
    useVoiceStore.getState().start('intake');
    for (let i = 0; i < 7; i++) useVoiceStore.getState().addCaption(`c${i}`);
    const captions = useVoiceStore.getState().captions;
    expect(captions).toHaveLength(5);
    expect(captions[4]).toBe('c6');
  });
});
