import { describe, it, expect, beforeEach, afterEach, mock } from 'bun:test';
import {
  ICE_SERVERS,
  ensureRemoteAudioElement,
  waitForIceGatheringComplete,
} from '@/lib/intake/webrtc';

describe('webrtc — ICE_SERVERS', () => {
  it('includes Google public STUN as a fallback', () => {
    const flat = JSON.stringify(ICE_SERVERS);
    expect(flat).toContain('stun');
  });
});

describe('webrtc — ensureRemoteAudioElement', () => {
  let originalDocument: any;
  beforeEach(() => {
    originalDocument = (globalThis as any).document;
    (globalThis as any).document = {
      _els: new Map(),
      getElementById(id: string) { return this._els.get(id) ?? null; },
      createElement(tag: string) {
        return { id: '', autoplay: false, style: {}, tag, srcObject: null };
      },
      body: { appendChild(el: any) { (globalThis as any).document._els.set(el.id, el); }, innerHTML: '' },
    };
  });
  afterEach(() => { (globalThis as any).document = originalDocument; });

  it('creates the audio element when missing', () => {
    const el = ensureRemoteAudioElement('v2-intake-voice-remote-audio');
    expect(el).not.toBeNull();
    expect((el as any).id).toBe('v2-intake-voice-remote-audio');
    expect((el as any).autoplay).toBe(true);
  });

  it('returns the existing element on second call', () => {
    const a = ensureRemoteAudioElement('v2-intake-voice-remote-audio');
    const b = ensureRemoteAudioElement('v2-intake-voice-remote-audio');
    expect(a).toBe(b);
  });
});

describe('webrtc — waitForIceGatheringComplete', () => {
  it('resolves immediately when iceGatheringState is already complete', async () => {
    const pc = { iceGatheringState: 'complete', addEventListener: mock(), removeEventListener: mock() } as unknown as RTCPeerConnection;
    await waitForIceGatheringComplete(pc, 100);
  });

  it('resolves after timeout if never complete', async () => {
    const pc = { iceGatheringState: 'gathering', addEventListener: mock(), removeEventListener: mock() } as unknown as RTCPeerConnection;
    const start = Date.now();
    await waitForIceGatheringComplete(pc, 50);
    expect(Date.now() - start).toBeGreaterThanOrEqual(40);
  });
});
