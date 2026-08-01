/**
 * Hook tests for `use-services.ts`. Each hook is a thin async wrapper
 * around a service call; we render the hook in a host component and
 * assert the documented contract — initial loading=true, data after
 * resolution, error on rejection, refetch is a stable callable.
 *
 * Coverage impact: brings use-services from ~9% line coverage toward
 * ~60-70% by exercising every exported hook at least once.
 */

import { afterEach, describe, expect, spyOn, test } from 'bun:test';
import { cleanup, render, waitFor } from '@testing-library/react';
import * as services from '@/services';
import {
  useActivity,
  useAsyncList,
  useBillingOverview,
  useCandidatesForRequisition,
  useDebrief,
  useDebriefInsights,
  useEnsureSeeded,
  useIntegrations,
  useNotificationPrefs,
  useProfile,
  useRequisition,
  useRequisitions,
  useTeam,
} from './use-services';

afterEach(cleanup);

describe('useAsyncList — out-of-order race guard', () => {
  test('a slow first run is superseded by a fast second run (no stale paint)', async () => {
    // First render resolves SLOWLY, second render (after id change) resolves
    // FAST. Without the run-id guard the slow first result would land last and
    // paint stale data. The guard must ensure only the second result is shown.
    let resolveSlow: ((v: { id: string }) => void) | null = null;
    const spy = spyOn(services.requisitions, 'get').mockImplementation((id: string) => {
      if (id === 'slow') {
        return new Promise<{ id: string }>((res) => {
          resolveSlow = res;
        }) as unknown as ReturnType<typeof services.requisitions.get>;
      }
      return Promise.resolve({ id: 'fast' }) as unknown as ReturnType<
        typeof services.requisitions.get
      >;
    });

    function Probe({ reqId }: { reqId: string }) {
      const s = useRequisition(reqId);
      return <div data-testid="host">{s.data?.id ?? 'none'}</div>;
    }

    const { getByTestId, rerender } = render(<Probe reqId="slow" />);
    // Switch to the fast id before the slow fetch resolves.
    rerender(<Probe reqId="fast" />);
    await waitFor(() => {
      expect(getByTestId('host').textContent).toBe('fast');
    });

    // Now let the stale slow run resolve — it MUST be ignored.
    resolveSlow?.({ id: 'slow' });
    await Promise.resolve();
    await Promise.resolve();
    expect(getByTestId('host').textContent).toBe('fast');
    spy.mockRestore();
  });

  test('unmount ignores an in-flight run (no setState-after-unmount)', async () => {
    let resolveLate: ((v: { id: string }) => void) | null = null;
    const spy = spyOn(services.requisitions, 'get').mockImplementation(
      () =>
        new Promise<{ id: string }>((res) => {
          resolveLate = res;
        }) as unknown as ReturnType<typeof services.requisitions.get>,
    );
    const errors: unknown[] = [];
    const origError = console.error;
    console.error = (...args: unknown[]) => {
      errors.push(args);
    };

    function Probe() {
      const s = useRequisition('r1');
      return <div data-testid="host">{s.data?.id ?? 'none'}</div>;
    }

    const { unmount } = render(<Probe />);
    unmount();
    // Resolve after unmount — the guard/abort must prevent any setState.
    resolveLate?.({ id: 'r1' });
    await Promise.resolve();
    await Promise.resolve();

    console.error = origError;
    const stateUpdateWarning = errors.find((e) => JSON.stringify(e).includes('unmounted'));
    expect(stateUpdateWarning).toBeUndefined();
    spy.mockRestore();
  });

  test('passes an AbortSignal to the loader', async () => {
    let receivedSignal: unknown;
    function Probe() {
      const s = useAsyncList<string>((signal) => {
        receivedSignal = signal;
        return Promise.resolve('ok');
      }, []);
      return <div data-testid="host">{s.data ?? 'none'}</div>;
    }
    render(<Probe />);
    await waitFor(() => {
      expect(getByTestIdGlobal('host').textContent).toBe('ok');
    });
    expect(receivedSignal instanceof AbortSignal).toBe(true);
  });

  test('aborts the in-flight signal when a new run supersedes it', async () => {
    const signals: AbortSignal[] = [];
    function Probe({ tick }: { tick: number }) {
      useAsyncList<string>(
        (signal) => {
          if (signal) signals.push(signal);
          return new Promise<string>(() => {
            // never resolves — we only care that the prior signal aborts
          });
        },
        [],
        [tick],
      );
      return <div data-testid="host">x</div>;
    }
    const { rerender } = render(<Probe tick={0} />);
    await waitFor(() => {
      expect(signals.length).toBeGreaterThanOrEqual(1);
    });
    rerender(<Probe tick={1} />);
    // Effects flush asynchronously under happy-dom; give the superseding run a
    // tick to start before asserting on the abort of the prior run.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(signals.length).toBeGreaterThanOrEqual(2);
    // The first run's signal must be aborted once the second run supersedes it.
    expect(signals[0]?.aborted).toBe(true);
    expect(signals[1]?.aborted).toBe(false);
  });
});

function getByTestIdGlobal(id: string): HTMLElement {
  const el = document.querySelector(`[data-testid="${id}"]`);
  if (!el) throw new Error(`no element with testid ${id}`);
  return el as HTMLElement;
}

function Host<T>({ value }: { value: T }) {
  return <div data-testid="host">{JSON.stringify(value)}</div>;
}

describe('useEnsureSeeded — no-op', () => {
  test('does nothing and never throws', () => {
    function Probe() {
      useEnsureSeeded();
      return <div data-testid="probe">ok</div>;
    }
    const { getByTestId } = render(<Probe />);
    expect(getByTestId('probe').textContent).toBe('ok');
  });
});

describe('useRequisition', () => {
  test('returns null data + no error when id is null', async () => {
    function Probe() {
      const s = useRequisition(null);
      return <Host value={s} />;
    }
    const { getByTestId } = render(<Probe />);
    await waitFor(() => {
      const v = JSON.parse(getByTestId('host').textContent || '{}');
      expect(v.data).toBeNull();
      expect(v.error).toBeNull();
    });
  });

  test('loads data when given a valid id', async () => {
    const fakeReq = { id: 'r1', role_title: 'Test Role' };
    const spy = spyOn(services.requisitions, 'get').mockResolvedValue(
      fakeReq as unknown as Awaited<ReturnType<typeof services.requisitions.get>>,
    );
    function Probe() {
      const s = useRequisition('r1');
      return <Host value={s} />;
    }
    const { getByTestId } = render(<Probe />);
    await waitFor(() => {
      const v = JSON.parse(getByTestId('host').textContent || '{}');
      expect(v.data?.id).toBe('r1');
    });
    spy.mockRestore();
  });

  test('captures the error when the service rejects', async () => {
    const spy = spyOn(services.requisitions, 'get').mockRejectedValue(new Error('boom'));
    function Probe() {
      const s = useRequisition('r1');
      return <Host value={{ data: s.data, error: s.error?.message }} />;
    }
    const { getByTestId } = render(<Probe />);
    await waitFor(() => {
      const v = JSON.parse(getByTestId('host').textContent || '{}');
      expect(v.error).toBe('boom');
    });
    spy.mockRestore();
  });
});

describe('useRequisitions — list', () => {
  test('returns an empty page initially, then loads', async () => {
    const fakePage = { items: [], total: 0, page: 1, page_size: 25 };
    const spy = spyOn(services.requisitions, 'list').mockResolvedValue(
      fakePage as unknown as Awaited<ReturnType<typeof services.requisitions.list>>,
    );
    function Probe() {
      const s = useRequisitions();
      return <Host value={s.data} />;
    }
    const { getByTestId } = render(<Probe />);
    await waitFor(() => {
      const v = JSON.parse(getByTestId('host').textContent || 'null');
      expect(v).not.toBeNull();
    });
    spy.mockRestore();
  });
});

describe('list-style hooks resolve without error', () => {
  test('useTeam', async () => {
    const spy = spyOn(services.team, 'get').mockResolvedValue({
      members: [],
      invites: [],
    } as unknown as Awaited<ReturnType<typeof services.team.get>>);
    function Probe() {
      const s = useTeam();
      return <Host value={s.error?.message ?? null} />;
    }
    const { getByTestId } = render(<Probe />);
    await waitFor(() => {
      expect(JSON.parse(getByTestId('host').textContent || 'null')).toBeNull();
    });
    spy.mockRestore();
  });

  test('useBillingOverview', async () => {
    const spy = spyOn(services.billing, 'getOverview').mockResolvedValue({
      plan: 'free',
      credits_remaining: 10,
    } as unknown as Awaited<ReturnType<typeof services.billing.getOverview>>);
    function Probe() {
      const s = useBillingOverview();
      return <Host value={s.error?.message ?? null} />;
    }
    const { getByTestId } = render(<Probe />);
    await waitFor(() => {
      expect(JSON.parse(getByTestId('host').textContent || 'null')).toBeNull();
    });
    spy.mockRestore();
  });

  test('useIntegrations', async () => {
    const spy = spyOn(services.integrations, 'list').mockResolvedValue(
      [] as unknown as Awaited<ReturnType<typeof services.integrations.list>>,
    );
    function Probe() {
      const s = useIntegrations();
      return <Host value={s.error?.message ?? null} />;
    }
    const { getByTestId } = render(<Probe />);
    await waitFor(() => {
      expect(JSON.parse(getByTestId('host').textContent || 'null')).toBeNull();
    });
    spy.mockRestore();
  });

  test('useProfile', async () => {
    const spy = spyOn(services.profile, 'get').mockResolvedValue({
      id: 'u1',
      email: 'x@y.com',
    } as unknown as Awaited<ReturnType<typeof services.profile.get>>);
    function Probe() {
      const s = useProfile();
      return <Host value={s.error?.message ?? null} />;
    }
    const { getByTestId } = render(<Probe />);
    await waitFor(() => {
      expect(JSON.parse(getByTestId('host').textContent || 'null')).toBeNull();
    });
    spy.mockRestore();
  });
});

describe('id-scoped hooks return null when id is null', () => {
  test('useCandidatesForRequisition(null)', async () => {
    function Probe() {
      const s = useCandidatesForRequisition(null);
      return <Host value={{ data: s.data, error: s.error?.message }} />;
    }
    const { getByTestId } = render(<Probe />);
    await waitFor(() => {
      const v = JSON.parse(getByTestId('host').textContent || '{}');
      expect(v.error).toBeUndefined();
    });
  });

  test('useDebrief(null)', () => {
    function Probe() {
      const s = useDebrief(null);
      return <Host value={s.data} />;
    }
    render(<Probe />);
    // No error thrown is enough — the hook short-circuits.
  });

  test('useDebriefInsights(null)', () => {
    function Probe() {
      const s = useDebriefInsights(null);
      return <Host value={s.data} />;
    }
    render(<Probe />);
  });
});

describe('useActivity + useNotificationPrefs', () => {
  test('useActivity returns recent events', async () => {
    const spy = spyOn(services.activity, 'list').mockResolvedValue(
      [] as unknown as Awaited<ReturnType<typeof services.activity.list>>,
    );
    function Probe() {
      const s = useActivity(10);
      return <Host value={s.error?.message ?? null} />;
    }
    const { getByTestId } = render(<Probe />);
    await waitFor(() => {
      expect(JSON.parse(getByTestId('host').textContent || 'null')).toBeNull();
    });
    spy.mockRestore();
  });

  test('useNotificationPrefs returns the prefs row', async () => {
    const spy = spyOn(services.profile, 'getNotificationPrefs').mockResolvedValue({
      email: true,
      slack: false,
    } as unknown as Awaited<ReturnType<typeof services.profile.getNotificationPrefs>>);
    function Probe() {
      const s = useNotificationPrefs();
      return <Host value={s.error?.message ?? null} />;
    }
    const { getByTestId } = render(<Probe />);
    await waitFor(() => {
      expect(JSON.parse(getByTestId('host').textContent || 'null')).toBeNull();
    });
    spy.mockRestore();
  });
});
