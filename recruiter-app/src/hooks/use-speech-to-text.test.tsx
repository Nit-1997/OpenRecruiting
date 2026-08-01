// FE-T1: coverage for useSpeechToText — the Deepgram live-STT dictation hook
// used on the interviewer feedback edit screen.
//
// The hook touches four external surfaces, all stubbed here:
//   1. fetch('/api/deepgram')        — BFF that mints a short-lived Deepgram key
//   2. @deepgram/sdk createClient    — opens a live transcription connection
//   3. navigator.mediaDevices.getUserMedia — mic capture
//   4. MediaRecorder                 — chunks mic audio to the connection
//
// happy-dom provides neither MediaRecorder nor navigator.mediaDevices, so we
// install minimal fakes per-test and restore them in afterEach (no leak). The
// Deepgram SDK is mocked process-wide via a controllable fake-connection
// registry; no other test file imports this hook, so there is no conflict.

import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { act, renderHook } from '@testing-library/react';

// ---- Controllable Deepgram fake -------------------------------------------
type Handler = (data?: unknown) => void;

interface FakeConnection {
  on: (event: string, cb: Handler) => void;
  send: (data: unknown) => void;
  requestClose: () => void;
  // test-only: fire a registered event
  __emit: (event: string, data?: unknown) => void;
  __sent: unknown[];
  __requestCloseCalls: number;
}

let lastConnection: FakeConnection | null = null;
let createClientCalls: Array<string> = [];

function makeFakeConnection(): FakeConnection {
  const handlers = new Map<string, Handler>();
  const conn: FakeConnection = {
    on: (event, cb) => {
      handlers.set(event, cb);
    },
    send: (data) => {
      conn.__sent.push(data);
    },
    requestClose: () => {
      conn.__requestCloseCalls += 1;
    },
    __emit: (event, data) => {
      handlers.get(event)?.(data);
    },
    __sent: [],
    __requestCloseCalls: 0,
  };
  return conn;
}

mock.module('@deepgram/sdk', () => ({
  LiveTranscriptionEvents: {
    Open: 'open',
    Close: 'close',
    Error: 'error',
    Transcript: 'Results',
  },
  createClient: (apiKey: string) => {
    createClientCalls.push(apiKey);
    return {
      listen: {
        live: () => {
          lastConnection = makeFakeConnection();
          return lastConnection;
        },
      },
    };
  },
}));

import { useSpeechToText } from './use-speech-to-text';

// ---- DOM media fakes -------------------------------------------------------
interface FakeTrack {
  stop: () => void;
}
let stoppedTracks = 0;
let getUserMediaImpl: () => Promise<{ getTracks: () => FakeTrack[] }>;
let lastRecorder: FakeRecorder | null = null;

class FakeRecorder {
  static isTypeSupported = (_t: string) => true;
  state: 'inactive' | 'recording' = 'inactive';
  ondataavailable: ((e: { data: { size: number } }) => void) | null = null;
  startCalls = 0;
  stopCalls = 0;
  constructor(
    public stream: unknown,
    public opts: { mimeType: string },
  ) {
    lastRecorder = this;
  }
  start(_timeslice?: number) {
    this.state = 'recording';
    this.startCalls += 1;
  }
  stop() {
    this.state = 'inactive';
    this.stopCalls += 1;
  }
}

const originalFetch = globalThis.fetch;

beforeEach(() => {
  lastConnection = null;
  lastRecorder = null;
  createClientCalls = [];
  stoppedTracks = 0;

  getUserMediaImpl = async () => ({
    getTracks: () => [{ stop: () => (stoppedTracks += 1) }],
  });

  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: () => getUserMediaImpl() },
  });
  (globalThis as { MediaRecorder?: unknown }).MediaRecorder = FakeRecorder as unknown;

  globalThis.fetch = mock(
    async () =>
      new Response(JSON.stringify({ apiKey: 'dg-key-123' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
  ) as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  // Restore the injected globals to happy-dom's default (absent). Assign rather
  // than `delete` so no leaked MediaRecorder/mediaDevices reaches another file.
  (globalThis as { MediaRecorder?: unknown }).MediaRecorder = undefined;
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: undefined,
  });
});

describe('useSpeechToText - initial state', () => {
  test('starts idle: not listening, not connecting, no error', () => {
    const { result } = renderHook(() => useSpeechToText());
    expect(result.current.isListening).toBe(false);
    expect(result.current.isConnecting).toBe(false);
    expect(result.current.error).toBeNull();
  });
});

describe('useSpeechToText - startListening happy path', () => {
  test('fetches the BFF key, opens a connection, then transitions to listening on Open', async () => {
    const transcripts: Array<{ text: string; final: boolean }> = [];
    const { result } = renderHook(() =>
      useSpeechToText({
        feedbackSessionToken: 'tok-feedback',
        onTranscript: (text, final) => transcripts.push({ text, final }),
      }),
    );

    await act(async () => {
      await result.current.startListening();
    });

    // Key was fetched from the BFF, with the feedback-session auth header.
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof mock>;
    expect(fetchMock.mock.calls.length).toBe(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/deepgram');
    expect((init.headers as Record<string, string>)['x-feedback-session']).toBe('tok-feedback');

    // The fetched key was handed to the Deepgram client.
    expect(createClientCalls).toEqual(['dg-key-123']);

    // Until Open fires, we are connecting (the connection is async).
    expect(result.current.isConnecting).toBe(true);
    expect(result.current.isListening).toBe(false);

    // Fire Open → starts MediaRecorder and flips to listening.
    act(() => {
      lastConnection?.__emit('open');
    });
    expect(result.current.isConnecting).toBe(false);
    expect(result.current.isListening).toBe(true);
    expect(lastRecorder?.startCalls).toBe(1);

    // A mic data chunk with size>0 is forwarded to the connection.
    act(() => {
      lastRecorder?.ondataavailable?.({ data: { size: 42 } });
    });
    expect(lastConnection?.__sent.length).toBe(1);

    // A zero-size chunk is NOT forwarded.
    act(() => {
      lastRecorder?.ondataavailable?.({ data: { size: 0 } });
    });
    expect(lastConnection?.__sent.length).toBe(1);

    // Transcript events surface final + interim to the caller.
    act(() => {
      lastConnection?.__emit('Results', {
        is_final: true,
        channel: { alternatives: [{ transcript: 'hello world' }] },
      });
      lastConnection?.__emit('Results', {
        is_final: false,
        channel: { alternatives: [{ transcript: 'partial' }] },
      });
      // empty transcript → ignored
      lastConnection?.__emit('Results', {
        is_final: true,
        channel: { alternatives: [{ transcript: '' }] },
      });
    });
    expect(transcripts).toEqual([
      { text: 'hello world', final: true },
      { text: 'partial', final: false },
    ]);
  });

  test('no feedback-session token → no x-feedback-session header is sent', async () => {
    const { result } = renderHook(() => useSpeechToText());
    await act(async () => {
      await result.current.startListening();
    });
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof mock>;
    const init = (fetchMock.mock.calls[0] as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>)['x-feedback-session']).toBeUndefined();
  });
});

describe('useSpeechToText - error paths', () => {
  test('BFF returns an error payload → surfaces the message, not connecting', async () => {
    globalThis.fetch = mock(
      async () =>
        new Response(JSON.stringify({ error: 'rate limited' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    ) as unknown as typeof fetch;

    const { result } = renderHook(() => useSpeechToText());
    await act(async () => {
      await result.current.startListening();
    });

    expect(result.current.error).toBe('rate limited');
    expect(result.current.isConnecting).toBe(false);
    expect(result.current.isListening).toBe(false);
  });

  test('BFF returns no key and no error → falls back to a default message', async () => {
    globalThis.fetch = mock(
      async () =>
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    ) as unknown as typeof fetch;

    const { result } = renderHook(() => useSpeechToText());
    await act(async () => {
      await result.current.startListening();
    });

    expect(result.current.error).toBe('Failed to get dictation key');
    expect(result.current.isConnecting).toBe(false);
  });

  test('getUserMedia rejection (mic denied) → surfaces the error and tears down', async () => {
    getUserMediaImpl = async () => {
      throw new Error('Permission denied');
    };

    const { result } = renderHook(() => useSpeechToText());
    await act(async () => {
      await result.current.startListening();
    });

    expect(result.current.error).toBe('Permission denied');
    expect(result.current.isConnecting).toBe(false);
    expect(result.current.isListening).toBe(false);
  });

  test('a Deepgram Error event sets the error and stops listening', async () => {
    const { result } = renderHook(() => useSpeechToText());
    await act(async () => {
      await result.current.startListening();
    });
    act(() => {
      lastConnection?.__emit('open');
    });
    expect(result.current.isListening).toBe(true);

    act(() => {
      lastConnection?.__emit('error');
    });
    expect(result.current.error).toBe('Dictation error — please try again.');
    expect(result.current.isListening).toBe(false);
  });

  test('a Deepgram Close event flips listening/connecting back off', async () => {
    const { result } = renderHook(() => useSpeechToText());
    await act(async () => {
      await result.current.startListening();
    });
    act(() => {
      lastConnection?.__emit('open');
    });
    expect(result.current.isListening).toBe(true);

    act(() => {
      lastConnection?.__emit('close');
    });
    expect(result.current.isListening).toBe(false);
    expect(result.current.isConnecting).toBe(false);
  });
});

describe('useSpeechToText - stopListening teardown', () => {
  test('stops the recorder, closes the connection, stops mic tracks, resets flags', async () => {
    const { result } = renderHook(() => useSpeechToText());
    await act(async () => {
      await result.current.startListening();
    });
    act(() => {
      lastConnection?.__emit('open');
    });

    const conn = lastConnection;
    const recorder = lastRecorder;
    expect(result.current.isListening).toBe(true);

    act(() => {
      result.current.stopListening();
    });

    expect(recorder?.stopCalls).toBe(1);
    expect(conn?.__requestCloseCalls).toBe(1);
    expect(stoppedTracks).toBe(1);
    expect(result.current.isListening).toBe(false);
    expect(result.current.isConnecting).toBe(false);
  });

  test('stopListening before starting is a safe no-op', () => {
    const { result } = renderHook(() => useSpeechToText());
    act(() => {
      result.current.stopListening();
    });
    expect(result.current.isListening).toBe(false);
    expect(stoppedTracks).toBe(0);
  });
});
