import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

let pathnameFixture = '/';
const pushMock = mock((_: string) => {});

mock.module('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => pathnameFixture,
}));

import { useComposerStore, useSessionStore, useShellStore } from '@/stores';
import { Composer } from './composer';

const originalFetch = globalThis.fetch;

function mockIntent(intent: string) {
  globalThis.fetch = mock(
    async () =>
      new Response(JSON.stringify({ intent }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
  ) as unknown as typeof fetch;
}

describe('Composer home submit', () => {
  beforeEach(() => {
    useShellStore.getState().reset();
    useSessionStore.getState().reset();
    useComposerStore.getState().reset();
    pathnameFixture = '/';
    pushMock.mockClear();
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
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
