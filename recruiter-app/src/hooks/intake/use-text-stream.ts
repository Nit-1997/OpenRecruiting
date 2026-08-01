'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  IntakeApiError,
  ModalityConflictError,
  openTextConversation,
  streamTextTurn,
} from '@/lib/intake/api';
import type { TextStreamEvent } from '@/types/intake';

export type TextStreamStatus = 'idle' | 'streaming' | 'error' | 'modality_conflict';

export type TextStreamDone = Extract<TextStreamEvent, { type: 'done' }>;

export interface UseTextStreamResult {
  status: TextStreamStatus;
  streamingText: string;
  error: { message: string; code?: string } | null;
  lastDone: TextStreamDone | null;
  /** Resolves true if the turn streamed to completion, false if it was dropped
   *  (busy / no session) or failed (error / modality conflict / abort). The
   *  composer uses this to keep the user's text instead of losing it. */
  send: (message: string) => Promise<boolean>;
  /** Trigger the agent's proactive opening greeting (no user message). */
  open: () => Promise<void>;
  cancel: () => void;
}

export function useTextStream(sessionId: string | null): UseTextStreamResult {
  const [status, setStatus] = useState<TextStreamStatus>('idle');
  const [streamingText, setStreamingText] = useState('');
  const [error, setError] = useState<{ message: string; code?: string } | null>(null);
  const [lastDone, setLastDone] = useState<TextStreamDone | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);

  // Shared consumer for both the message stream and the opening stream — same
  // state machine, only the source generator differs.
  const consume = useCallback(
    async (
      makeStream: (signal: AbortSignal) => AsyncGenerator<TextStreamEvent>,
    ): Promise<boolean> => {
      if (!sessionId) {
        setError({ message: 'no active session' });
        setStatus('error');
        return false;
      }
      // Busy: a stream is already in flight (e.g. the floor-rule greeting fired
      // on a modality switch before React disabled the composer). Report the
      // drop so the caller can keep the user's text instead of silently losing it.
      if (inFlightRef.current) return false;

      inFlightRef.current = true;
      setStreamingText('');
      setError(null);
      setLastDone(null);
      setStatus('streaming');

      const controller = new AbortController();
      abortRef.current = controller;

      let ok = false;
      try {
        for await (const ev of makeStream(controller.signal)) {
          if (ev.type === 'text') {
            setStreamingText((prev) => prev + ev.chunk);
          } else if (ev.type === 'done') {
            setLastDone(ev);
            setStatus('idle');
            ok = true;
          } else if (ev.type === 'error') {
            setError({ message: ev.message, ...(ev.code ? { code: ev.code } : {}) });
            setStatus('error');
            ok = false;
          }
        }
        setStatus((prev) => (prev === 'streaming' ? 'idle' : prev));
      } catch (e: unknown) {
        if (e instanceof ModalityConflictError) {
          setError({ message: e.detail, code: 'modality_conflict' });
          setStatus('modality_conflict');
          return false;
        }
        if ((e as Error)?.name === 'AbortError') {
          setStatus('idle');
          return false;
        }
        const msg =
          e instanceof IntakeApiError ? e.detail : e instanceof Error ? e.message : 'stream failed';
        setError({ message: msg });
        setStatus('error');
        return false;
      } finally {
        inFlightRef.current = false;
        abortRef.current = null;
      }
      return ok;
    },
    [sessionId],
  );

  const send = useCallback(
    async (message: string): Promise<boolean> => {
      if (!message.trim()) return false;
      const sid = sessionId;
      if (!sid) {
        setError({ message: 'no active session' });
        setStatus('error');
        return false;
      }
      return consume((signal) => streamTextTurn(sid, message, signal));
    },
    [sessionId, consume],
  );

  const open = useCallback(async () => {
    const sid = sessionId;
    if (!sid) return;
    await consume((signal) => openTextConversation(sid, signal));
  }, [sessionId, consume]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return { status, streamingText, error, lastDone, send, open, cancel };
}
