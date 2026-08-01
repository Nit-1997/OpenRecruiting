import { beforeEach, describe, expect, test } from 'bun:test';
import type { RoleFixture } from '@/fixtures/roles';
import { cancelRun } from '@/lib/sub-agent-runner';
import { useArtifactStore, useSessionStore } from '@/stores';
import { runCortexInsight as brainRunCortexInsight } from './brain/flow';
import { pickRoleForSourcing, runStrategyAndChannels } from './sourcing/flow';

const DEMO_ROLE: RoleFixture = {
  id: 'pm-sfo',
  title: 'Staff PM · Sunnyvale',
  loc: 'Full-time · Product',
  pipeline: '4 candidates awaiting decision',
  status: 'live',
  dept: 'Product',
  owner: 'Nitin',
  created_at: '2026-03-22T14:30:00Z',
  ready_to_debrief: true,
  must_have: ['Product strategy'],
  nice_to_have: [],
};

/** Wrap a store action so we can count how many times it fires. */
function countCalls<T extends (...args: never[]) => unknown>(
  obj: Record<string, unknown>,
  key: string,
): { restore: () => void; count: () => number } {
  const original = obj[key] as T;
  let calls = 0;
  obj[key] = ((...args: Parameters<T>) => {
    calls += 1;
    return original(...args);
  }) as T;
  return {
    restore: () => {
      obj[key] = original;
    },
    count: () => calls,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

beforeEach(() => {
  useSessionStore.getState().reset();
  useArtifactStore.getState().reset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

describe('sub-agent flow cancellation', () => {
  test('sourcing: aborting mid runStrategyAndChannels freezes artifact patches', async () => {
    useSessionStore.getState().startSession('sourcing', 'preferences_chat');
    useSessionStore.getState().updateSelections('sourcing', {
      mode: 'existing',
      roleId: 'pm-sfo',
      roleTitle: 'Staff PM · Sunnyvale',
    });

    const sessions = useSessionStore.getState() as unknown as Record<string, unknown>;
    const artifacts = useArtifactStore.getState() as unknown as Record<string, unknown>;
    const patchSpy = countCalls(artifacts, 'patchArtifact');
    const appendSpy = countCalls(sessions, 'appendMessage');

    const running = runStrategyAndChannels('Some preferences');
    // Let a couple of trail steps run, then navigate away (unmount → cancelRun).
    await sleep(120);
    cancelRun('sourcing');
    const patchesAtAbort = patchSpy.count();
    const appendsAtAbort = appendSpy.count();

    await running;
    // No further store mutations after the abort.
    expect(patchSpy.count()).toBe(patchesAtAbort);
    expect(appendSpy.count()).toBe(appendsAtAbort);

    patchSpy.restore();
    appendSpy.restore();
  });

  test('sourcing: two runs do not share a token — the first bails', async () => {
    useSessionStore.getState().startSession('sourcing', 'preferences_chat');
    useSessionStore.getState().updateSelections('sourcing', {
      mode: 'existing',
      roleId: 'pm-sfo',
      roleTitle: 'Staff PM · Sunnyvale',
    });

    const artifacts = useArtifactStore.getState() as unknown as Record<string, unknown>;
    const patchSpy = countCalls(artifacts, 'patchArtifact');

    const first = runStrategyAndChannels('first');
    await sleep(80);
    // A second run starts (e.g. fast remount) — this must abort the first.
    const second = runStrategyAndChannels('second');
    const patchesWhenSecondStarted = patchSpy.count();
    await first;
    // The first run produced no additional patches after the second took over.
    // (It bailed on its next signal.aborted check.)
    const patchesAfterFirstSettled = patchSpy.count();
    cancelRun('sourcing');
    await second;

    // The first run did not keep patching after the second began. We allow a
    // tiny slack of 1 in case a patch was already scheduled at the boundary.
    expect(patchesAfterFirstSettled - patchesWhenSecondStarted).toBeLessThanOrEqual(1);

    patchSpy.restore();
  });

  test('brain: aborting mid runCortexInsight freezes appendMessage', async () => {
    useSessionStore.getState().startSession('brain', 'brain');

    const sessions = useSessionStore.getState() as unknown as Record<string, unknown>;
    const artifacts = useArtifactStore.getState() as unknown as Record<string, unknown>;
    const appendSpy = countCalls(sessions, 'appendMessage');
    const patchSpy = countCalls(artifacts, 'patchArtifact');

    const running = brainRunCortexInsight('close_rate');
    // Cortex trail opens with a long thinking pause; abort almost immediately.
    await sleep(50);
    cancelRun('brain');
    const appendsAtAbort = appendSpy.count();
    const patchesAtAbort = patchSpy.count();

    await running;
    expect(appendSpy.count()).toBe(appendsAtAbort);
    expect(patchSpy.count()).toBe(patchesAtAbort);

    appendSpy.restore();
    patchSpy.restore();
  });

  test('pickRoleForSourcing still completes the live happy path (no premature abort)', async () => {
    useSessionStore.getState().startSession('sourcing', 'role_pick');
    await pickRoleForSourcing(DEMO_ROLE);
    const session = useSessionStore.getState().sessions.sourcing;
    expect(session?.stage).toBe('preferences_chat');
  });
});
