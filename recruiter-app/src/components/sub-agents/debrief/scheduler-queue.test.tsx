/**
 * SchedulerQueue — walks a multi-candidate scheduling ask one PacketDrawer at
 * a time. The drawer's data hooks are spied to a harmless empty state (the
 * drawer.smoke.test.tsx pattern); these tests cover the queue chrome: the
 * "Scheduling N of M" bar, Next advancing the store, Done finishing it, and
 * the single-candidate case rendering no bar at all.
 */

import { afterEach, beforeEach, describe, expect, spyOn, test } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ConfirmDialogProvider } from '@/components/ui/confirm-dialog';
import * as services from '@/hooks/use-services';
import { useSessionStore } from '@/stores';
import type { SchedulerQueueState } from './flow';
import { SchedulerQueue } from './scheduler-queue';

let spies: Array<ReturnType<typeof spyOn>> = [];

const EMPTY_HOOK = {
  data: null,
  loading: false,
  error: null,
  refetch: () => {},
};

beforeEach(() => {
  useSessionStore.getState().reset();
  spies = (['usePacket', 'useRequisition', 'useRecording'] as const).map(
    (name) =>
      spyOn(services, name).mockReturnValue(
        EMPTY_HOOK as unknown as ReturnType<(typeof services)[typeof name]>,
      ),
  );
});

afterEach(() => {
  for (const spy of spies) spy.mockRestore();
  cleanup();
});

const POOL = [
  { id: 'cand-zara', name: 'Zara Sheikh' },
  { id: 'cand-ali', name: 'Ali Hussain' },
];

function seedQueue(candidateIds: string[]): void {
  const store = useSessionStore.getState();
  store.startSession('debrief', 'result');
  store.updateSelections('debrief', {
    roleId: 'role-1',
    candidatePool: POOL,
    schedulerQueue: { candidateIds, index: 0 },
  });
}

function QueueReader() {
  const queue = useSessionStore(
    (s) => s.sessions.debrief?.selections.schedulerQueue as SchedulerQueueState | null | undefined,
  );
  if (!queue) return <div data-testid="queue-closed" />;
  return <SchedulerQueue id="sq" roleId="role-1" queue={queue} />;
}

function Harness() {
  // The drawer's useConfirm needs the provider — in the app it comes from the
  // (shell) layout; mirror that here.
  return (
    <ConfirmDialogProvider>
      <QueueReader />
    </ConfirmDialogProvider>
  );
}

describe('SchedulerQueue', () => {
  test('multi-candidate queue shows the progress bar with the next candidate name', () => {
    seedQueue(['cand-zara', 'cand-ali']);
    render(<Harness />);
    expect(screen.getByText(/Scheduling 1 of 2/)).toBeTruthy();
    expect(screen.getByText(/Next: Ali Hussain/)).toBeTruthy();
  });

  test('Next advances to the second candidate; Done finishes and leaves a chat pointer', () => {
    seedQueue(['cand-zara', 'cand-ali']);
    render(<Harness />);

    fireEvent.click(screen.getByText(/Next: Ali Hussain/));
    expect(screen.getByText(/Scheduling 2 of 2/)).toBeTruthy();

    fireEvent.click(screen.getByText('Done'));
    expect(screen.getByTestId('queue-closed')).toBeTruthy();
    const msgs = useSessionStore.getState().sessions.debrief?.messages ?? [];
    expect(msgs.at(-1)?.text).toContain('Scheduling done');
  });

  test('a single-candidate queue renders the drawer without the bar', () => {
    seedQueue(['cand-zara']);
    render(<Harness />);
    expect(screen.queryByText(/Scheduling 1 of/)).toBeNull();
  });
});
