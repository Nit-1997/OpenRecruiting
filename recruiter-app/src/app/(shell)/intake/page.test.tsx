import { beforeEach, describe, expect, mock, test } from 'bun:test';
import { render, waitFor } from '@testing-library/react';

mock.module('next/navigation', () => ({
  useRouter: () => ({ push: () => {}, replace: () => {} }),
  usePathname: () => '/intake',
  useSearchParams: () => ({ get: () => null }),
}));

// Use the REAL intake store (not a module mock). Its default state already
// gives sessionId=null / no active modality, which is exactly the no-session
// path these tests assert. We deliberately do NOT mock.module it: bun's
// mock.module is process-wide and a stubbed store would leak into other intake
// test files (use-voice-call asserts on real setVoiceError behavior). We reset
// it in beforeEach so any state another file left behind can't bleed in.
import { useIntakeStore } from '@/stores/intake-store';

const intakeInitialState = useIntakeStore.getState();
beforeEach(() => {
  useIntakeStore.setState(intakeInitialState, true);
});

// Stub ONE layer deeper than the hook. Mocking `@/hooks/intake/use-intake-session`
// directly is unstable under bun: `mock.module` is process-wide, and other test
// files (e.g. use-process-till-now.test.tsx) import the REAL `useIntakeSession`
// through their own module graph. When they share this process, the direct hook
// mock loses the resolution race intermittently, so the canvas tree (which calls
// `useIntakeSession` in canvas.tsx AND in useProcessTillNow) flips between the
// 0-hook mock and the 4-hook real implementation BETWEEN renders — a React
// hooks-order violation. Mocking the deeper `@/lib/intake/realtime` dependency
// keeps the REAL hook running consistently (stable hook count) with its
// subscription stubbed to never push a session, so `session` stays null — the
// no-session path these tests assert. (use-process-till-now.test.tsx documents
// the same "go one layer deeper" lesson.)
mock.module('@/lib/intake/realtime', () => ({
  subscribeIntakeSession: () => ({ unsubscribe: () => {} }),
}));

mock.module('@/hooks/intake/use-intake-call', () => ({
  useIntakeCall: () => ({
    status: 'idle' as const,
    agentState: 'listening' as const,
    activeSessionId: null,
    pausedSessionMeta: null,
    pausedAt: null,
    isMuted: false,
    statusRef: { current: 'idle' as const },
    start: async () => {},
    pause: async () => {},
    resume: async () => {},
    end: async () => {},
    toggleMute: () => {},
  }),
}));

mock.module('@/stores/shell-store', () => {
  const { create } = require('zustand');
  const store = create(() => ({
    activeTabId: null as string | null,
    activeRailId: null,
    railDetail: null,
    stashed: null,
    setActiveTab: (_id: string | null) => {},
    setActiveRail: (_id: string | null) => {},
    closeRail: () => {},
    setRailDetail: (_detail: unknown) => {},
    goHome: () => {},
    reset: () => {},
    mode: () => 'agentic' as const,
  }));
  return { useShellStore: store };
});

mock.module('@/stores/composer-store', () => {
  const { create } = require('zustand');
  const store = create(() => ({
    value: '',
    scope: { kind: 'home' as const },
    uploading: null,
    setValue: (_v: string) => {},
    clearValue: () => {},
    setHomeScope: () => {},
    setAgenticScope: (_tabId: string) => {},
    setQnaScope: (_railId: string) => {},
    setUploading: (_file: File | null) => {},
    reset: () => {},
  }));
  return { useComposerStore: store };
});

mock.module('@/stores/active-context-store', () => ({
  useActiveContextStore: (sel: (s: unknown) => unknown) =>
    sel({ context: null, setContext: () => {}, clearContext: () => {} }),
}));

mock.module('@/hooks/intake/use-intake-sessions-list', () => ({
  useIntakeSessionsList: () => ({
    sessions: [],
    isLoading: false,
    error: null,
    refetch: async () => {},
  }),
}));

import IntakePage from './page';

describe('IntakePage', () => {
  test('renders intake canvas inline in the global chat shell (no contained chat box)', async () => {
    render(<IntakePage />);
    await waitFor(() => {
      expect(document.getElementById('intake-canvas')).not.toBeNull();
    });
  });

  test('renders lobby stage when no session is active', async () => {
    render(<IntakePage />);
    await waitFor(() => {
      expect(document.getElementById('intake-canvas-stage-hub')).not.toBeNull();
    });
  });

  test('does not render the old contained chat box or its own composer', async () => {
    render(<IntakePage />);
    await waitFor(() => {
      expect(document.getElementById('intake-page')).toBeNull();
      expect(document.getElementById('intake-page-chat-section')).toBeNull();
      expect(document.getElementById('intake-lobby-input-wrap')).toBeNull();
    });
  });
});
