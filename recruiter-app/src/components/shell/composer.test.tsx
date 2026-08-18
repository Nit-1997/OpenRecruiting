import { beforeEach, describe, expect, mock, test } from 'bun:test';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

let pathnameFixture = '/';
const pushMock = mock((_: string) => {});

mock.module('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => pathnameFixture,
}));

import { useComposerStore, useSessionStore, useShellStore } from '@/stores';
import { Composer } from './composer';

// Stubbed at the composer's DIRECT collaborator, not two layers below it.
//
// This used to assign `globalThis.fetch` and let the real
// classifyAssistantIntent -> v2Client.post -> fetch chain run. That silently
// stopped working in a full-suite run: `mock.module` is process-wide and
// last-writer-wins, and bun loads EVERY test file's top-level mocks before
// running any test, so `@/lib/v2-client` — which seven files stub — resolved to
// auth-store.test.ts's stub, whose `post` returns null. `res.intent` then threw
// a TypeError, assistant.ts's fail-open catch turned it into 'out_of_scope',
// and no route was pushed. Both routing tests failed with "not called" while
// passing in isolation.
//
// Mocking the seam the composer actually calls removes that dependency: these
// tests are about which ROUTE an intent produces, and `@/services/assistant` is
// imported by composer.tsx alone, so this registration cannot be outbid or leak
// into another file.
//
// KNOWN GAP, stated rather than papered over: classifyAssistantIntent's own HTTP
// behaviour — including the fail-open — is now covered by nothing. It cannot be
// tested robustly as it stands, because assistant.ts binds `v2Client` from the
// module namespace that seven test files mutate, so any direct test of it loses
// the same race this comment describes. Closing it needs either dependency
// injection in assistant.ts or another preload snapshot in src/test-setup.ts.
let intentFixture = 'out_of_scope';

mock.module('@/services/assistant', () => ({
  classifyAssistantIntent: async () => intentFixture,
}));

function mockIntent(intent: string) {
  intentFixture = intent;
}

describe('Composer home submit', () => {
  beforeEach(() => {
    useShellStore.getState().reset();
    useSessionStore.getState().reset();
    useComposerStore.getState().reset();
    pathnameFixture = '/';
    intentFixture = 'out_of_scope';
    pushMock.mockClear();
  });

  test('browse_roles intent routes to /view/roles', async () => {
    mockIntent('browse_roles');
    render(<Composer id="c" />);
    useComposerStore.getState().setHomeScope();
    useComposerStore.getState().setValue('show me my open roles');
    fireEvent.submit(screen.getByRole('form'));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith('/view/roles'));
  });

  test('intake_call intent seeds intake and routes to /intake', async () => {
    mockIntent('intake_call');
    render(<Composer id="c" />);
    useComposerStore.getState().setHomeScope();
    useComposerStore.getState().setValue('create a new data scientist role');
    fireEvent.submit(screen.getByRole('form'));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith('/intake'));
    expect(useSessionStore.getState().sessions.intake).toBeTruthy();
  });

  test('out_of_scope shows an agent reply with the two routing chips', async () => {
    mockIntent('out_of_scope');
    render(<Composer id="c" />);
    useComposerStore.getState().setHomeScope();
    useComposerStore.getState().setValue('what can you do for me today?');
    fireEvent.submit(screen.getByRole('form'));
    await waitFor(() => {
      const home = useSessionStore.getState().sessions.home;
      const chat = home?.messages.filter((m) => m.source === 'chat') ?? [];
      expect(chat.length).toBe(2);
    });
    const home = useSessionStore.getState().sessions.home;
    const agent = home?.messages.find((m) => m.role === 'agent');
    expect(agent?.chips?.map((c) => c.value)).toEqual(['/view/roles', 'intake']);
    expect(pushMock).not.toHaveBeenCalled();
  });

  test('intake scope is a no-op in the composer (the Hub drives intake)', () => {
    pathnameFixture = '/intake';
    render(<Composer id="c" />);
    useComposerStore.getState().setAgenticScope('intake');
    useComposerStore.getState().setValue('create a data scientist role');
    fireEvent.submit(screen.getByRole('form'));
    expect(pushMock).not.toHaveBeenCalled();
  });

  test('the attach "+" button is removed, the mic remains', () => {
    render(<Composer id="c" />);
    expect(screen.queryByLabelText('Attach file')).toBeNull();
    expect(screen.getByLabelText('Voice to text')).toBeTruthy();
  });

  test('no mic-error line is shown when there is no error', () => {
    render(<Composer id="c" />);
    expect(document.getElementById('c-mic-error')).toBeNull();
  });
});
