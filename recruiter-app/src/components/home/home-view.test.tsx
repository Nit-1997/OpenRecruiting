import { beforeEach, describe, expect, mock, test } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';

const pushMock = mock((_: string) => {});

mock.module('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => '/',
}));

import { makeMessage } from '@/lib/sub-agent-runner';
import { useComposerStore, useSessionStore } from '@/stores';
import type { Message } from '@/types';
import { HomeView } from './home-view';

const OUT_OF_SCOPE_CHIPS = [
  { label: 'Browse open roles', value: '/view/roles', primary: true },
  { label: 'Start an intake call', value: 'intake' },
];

// Seed a home agent message carrying the two out-of-scope routing chips and
// return it (for its id). The chips render in HomeView's `since` tail as
// buttons with id `home-post-m-<msgId>-chip-<value>`.
function seedOutOfScopeChips(): Message {
  useSessionStore.getState().startSession('home', 'brain');
  const msg = makeMessage(
    'agent',
    'Here are a couple of things I can do.',
    'text',
    'chat',
    OUT_OF_SCOPE_CHIPS,
  );
  useSessionStore.getState().appendMessage('home', msg);
  return msg;
}

describe('HomeView', () => {
  beforeEach(() => {
    useSessionStore.getState().reset();
    useComposerStore.getState().reset();
    useComposerStore.getState().setAgenticScope('intake');
    pushMock.mockClear();
  });

  test('resets composer scope to home on mount', () => {
    render(<HomeView id="home" />);
    expect(useComposerStore.getState().scope.kind).toBe('home');
  });

  test('clicking the browse-roles chip routes to /view/roles (no double slash)', () => {
    const msg = seedOutOfScopeChips();
    const { container } = render(<HomeView id="home" />);

    const chip = container.querySelector<HTMLButtonElement>(
      `#home-post-m-${msg.id}-chip-\\/view\\/roles`,
    );
    expect(chip).not.toBeNull();
    fireEvent.click(chip as HTMLButtonElement);

    expect(pushMock).toHaveBeenCalledWith('/view/roles');
    // A '/'-path chip must NOT start a sub-agent session.
    expect(useSessionStore.getState().sessions.intake).toBeFalsy();
  });

  test('clicking the intake chip seeds the intake session and routes to /intake', () => {
    const msg = seedOutOfScopeChips();
    const { container } = render(<HomeView id="home" />);

    const chip = container.querySelector<HTMLButtonElement>(`#home-post-m-${msg.id}-chip-intake`);
    expect(chip).not.toBeNull();
    fireEvent.click(chip as HTMLButtonElement);

    expect(pushMock).toHaveBeenCalledWith('/intake');
    expect(useSessionStore.getState().sessions.intake).toBeTruthy();
  });
});
