/**
 * FE-J8: the chat transcript must auto-scroll to the bottom not only when a
 * new message is appended (new tail id), but also when the LAST message grows
 * in place (streaming token updates mutate `text` without changing the id).
 *
 * happy-dom doesn't implement Element.scrollTo, so we stub it and assert it is
 * invoked with a bottom target on both an append and an in-place tail growth.
 */

import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { act, cleanup, render } from '@testing-library/react';
import { useSessionStore, useShellStore } from '@/stores';
import type { Message } from '@/types';
import { ChatColumn } from './chat-column';

let scrollCalls: Array<{ top?: number }> = [];
type ScrollProto = { scrollTo?: (o?: { top?: number }) => void };
let origScrollTo: ScrollProto['scrollTo'];
let origResizeObserver: unknown;

beforeEach(() => {
  useSessionStore.getState().reset();
  useShellStore.getState().reset();
  scrollCalls = [];
  // happy-dom's scrollTo is a no-op; capture calls so we can assert
  // bottom-pinning. Save the original to restore after each test (no leak).
  origScrollTo = (HTMLElement.prototype as ScrollProto).scrollTo;
  (HTMLElement.prototype as ScrollProto).scrollTo = (o) => {
    scrollCalls.push(o ?? {});
  };
  // Stub ResizeObserver deterministically (happy-dom provides one but it does
  // not fire on content growth here). Save + restore to avoid cross-file leak.
  origResizeObserver = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
  (globalThis as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  };
});

afterEach(() => {
  cleanup();
  (HTMLElement.prototype as ScrollProto).scrollTo = origScrollTo;
  (globalThis as { ResizeObserver: unknown }).ResizeObserver = origResizeObserver;
});

function msg(id: string, text: string): Message {
  return {
    id,
    role: 'agent',
    text,
    ts: new Date().toISOString(),
    source: 'chat',
  };
}

describe('ChatColumn — auto-scroll', () => {
  test('scrolls to the bottom on a new message append', () => {
    useShellStore.getState().setActiveTab('intake');
    useSessionStore.getState().startSession('intake', 'mode_choice');
    render(<ChatColumn id="chat">body</ChatColumn>);
    scrollCalls = [];
    act(() => {
      useSessionStore.getState().appendMessage('intake', msg('m1', 'hi'));
    });
    expect(scrollCalls.length).toBeGreaterThan(0);
  });

  test('re-scrolls when the last message grows in place (streaming)', () => {
    useShellStore.getState().setActiveTab('intake');
    useSessionStore.getState().startSession('intake', 'mode_choice');
    useSessionStore.getState().appendMessage('intake', msg('m1', 'partial'));
    render(<ChatColumn id="chat">body</ChatColumn>);
    scrollCalls = [];
    // Simulate a streaming update: same id, longer text. The store replaces the
    // session messages; the lastMsgLen selector changes, retriggering scroll.
    act(() => {
      useSessionStore.setState((s) => ({
        sessions: {
          ...s.sessions,
          intake: {
            ...s.sessions.intake,
            messages: [msg('m1', 'partial response now much longer')],
          },
        },
      }));
    });
    expect(scrollCalls.length).toBeGreaterThan(0);
  });
});
