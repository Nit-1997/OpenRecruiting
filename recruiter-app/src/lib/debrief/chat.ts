// SSE chat client for the debrief conversation agent (spec §7, Task 1.8).
//
// Mirrors `lib/debrief/api.ts`'s transport idiom EXACTLY — the shared v2 base
// (`getV2ApiBase`), the shared token resolver (`resolveV2Token`), and the shared
// 401-refresh hook (`runV2UnauthorizedHandler`) — so this layer is immune to the
// process-wide `mock.module('@/lib/v2-client')` stubs other test files install.
// The chat endpoint returns `text/event-stream` (not JSON), so it reads the
// response body stream directly rather than going through `api.ts`'s `request`.

import { getV2ApiBase } from '@/lib/env';
import { resolveV2Token, runV2UnauthorizedHandler } from '@/lib/v2-client';
import type { ProposedAction } from '@/types/sub-agent';
import { DebriefApiError } from './api';

/** A propose-tool payload streamed mid-turn (Phase 2 renders a rich confirm
 *  card; this phase summarizes it as a plain agent message). */
export interface DebriefProposedAction {
  kind: string;
  input: Record<string, unknown>;
}

export interface OpenDebriefChatOptions {
  onToken: (token: string) => void;
  onProposed: (proposed: DebriefProposedAction) => void;
  onError?: (message: string) => void;
  signal?: AbortSignal;
}

interface SseFrame {
  type: 'token' | 'proposed_action' | 'done' | 'error';
  data: unknown;
}

const STATIC_FAILURE = 'Something went wrong talking to OpenRecruiting. Please try again.';

function chatUrl(packetId: string): string {
  return `${getV2ApiBase()}/api/v2/debrief/packets/${packetId}/chat`;
}

function actionsUrl(packetId: string): string {
  return `${getV2ApiBase()}/api/v2/debrief/packets/${packetId}/actions`;
}

/** Result of a confirmed action — the `/actions` body is otherwise opaque to
 *  the FE (§4); we only surface `ok` + an optional `result`. */
export interface ExecuteActionResult {
  ok: boolean;
  result?: unknown;
}

/**
 * Execute a confirmed debrief action (spec §4). POSTs the SAME `{ kind, input }`
 * the `proposed_action` event delivered to `/api/v2/debrief/packets/{id}/actions`,
 * routed through the shared v2 base + token + one 401-refresh replay (the exact
 * idiom `lib/debrief/api.ts` uses). On any non-2xx throws a `DebriefApiError`
 * carrying the status so the caller can pick a friendly message — the raw
 * server text is never surfaced to the user.
 */
export async function executeDebriefAction(
  packetId: string,
  action: ProposedAction,
): Promise<ExecuteActionResult> {
  const url = actionsUrl(packetId);
  const send = async (): Promise<Response> => {
    const token = await resolveV2Token();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    return fetch(url, {
      method: 'POST',
      headers,
      credentials: 'include',
      cache: 'no-store',
      body: JSON.stringify({ kind: action.kind, input: action.input }),
    });
  };

  let res: Response;
  try {
    res = await send();
    if (res.status === 401) {
      const refreshed = await runV2UnauthorizedHandler();
      if (refreshed) res = await send();
    }
  } catch (e) {
    // Network / abort — a status-0 error so the caller routes to the generic
    // "couldn't apply that" message without leaking the raw cause.
    throw new DebriefApiError(0, (e as Error).message || 'Network error');
  }

  if (!res.ok) {
    // Drain the body so the socket frees, but NEVER surface raw server text.
    try {
      await res.json();
    } catch {
      // not JSON; ignore
    }
    throw new DebriefApiError(res.status, `action failed (${res.status})`);
  }

  if (res.status === 204) return { ok: true };
  const body = (await res.json()) as ExecuteActionResult;
  return { ok: body?.ok ?? true, result: body?.result };
}

/**
 * Open the debrief chat SSE stream for one turn. POSTs `{ message }`, reads the
 * `text/event-stream` body, splits on the SSE frame boundary (`\n\n`), parses
 * each `data: <json>` line, and dispatches by `type`. Buffers across reads so a
 * frame split between two chunks is reassembled. Network/parse failures call
 * `onError` with a STATIC message — never throws raw to the caller.
 */
export async function openDebriefChat(
  packetId: string,
  message: string,
  opts: OpenDebriefChatOptions,
): Promise<void> {
  const url = chatUrl(packetId);

  const send = async (): Promise<Response> => {
    const token = await resolveV2Token();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    const init: RequestInit = {
      method: 'POST',
      headers,
      credentials: 'include',
      cache: 'no-store',
      body: JSON.stringify({ message }),
    };
    if (opts.signal) init.signal = opts.signal;
    return fetch(url, init);
  };

  let res: Response;
  try {
    res = await send();
    if (res.status === 401) {
      const refreshed = await runV2UnauthorizedHandler();
      if (refreshed) res = await send();
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return;
    opts.onError?.(STATIC_FAILURE);
    return;
  }

  if (!res.ok || !res.body) {
    opts.onError?.(STATIC_FAILURE);
    return;
  }

  try {
    await consumeStream(res.body, opts);
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return;
    opts.onError?.(STATIC_FAILURE);
  }
}

function dispatchFrame(frame: SseFrame, opts: OpenDebriefChatOptions): void {
  switch (frame.type) {
    case 'token':
      if (typeof frame.data === 'string') opts.onToken(frame.data);
      break;
    case 'proposed_action': {
      const d = frame.data as { kind?: unknown; input?: unknown } | null;
      if (d && typeof d.kind === 'string') {
        opts.onProposed({
          kind: d.kind,
          input: d.input && typeof d.input === 'object' ? (d.input as Record<string, unknown>) : {},
        });
      }
      break;
    }
    case 'error': {
      const d = frame.data as { message?: unknown } | null;
      opts.onError?.(typeof d?.message === 'string' ? d.message : STATIC_FAILURE);
      break;
    }
    case 'done':
      break;
  }
}

function parseFrame(raw: string): SseFrame | null {
  // Each SSE frame may carry multiple lines; we only consume `data:` lines.
  const dataLines = raw
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice('data:'.length).trimStart());
  if (dataLines.length === 0) return null;
  const payload = dataLines.join('\n');
  try {
    const parsed = JSON.parse(payload) as SseFrame;
    if (parsed && typeof parsed.type === 'string') return parsed;
  } catch {
    // Malformed frame — skip it rather than aborting the whole stream.
  }
  return null;
}

async function consumeStream(
  body: ReadableStream<Uint8Array>,
  opts: OpenDebriefChatOptions,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line ("\n\n"). Flush every complete
      // frame; keep the trailing partial frame in the buffer for the next read.
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const rawFrame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const frame = parseFrame(rawFrame);
        if (frame) dispatchFrame(frame, opts);
        boundary = buffer.indexOf('\n\n');
      }
    }
  } finally {
    reader.releaseLock();
  }

  // Flush any trailing frame not terminated by a blank line.
  const tail = buffer.trim();
  if (tail) {
    const frame = parseFrame(tail);
    if (frame) dispatchFrame(frame, opts);
  }
}
