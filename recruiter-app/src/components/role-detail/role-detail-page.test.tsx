// Tests for the one-shot retry on transient 404 in RoleDetailPage.
//
// Strategy: mock the entire `@/hooks/use-services` module. We control what
// `useRequisition` returns on each render by tracking render-count in a
// module-level variable. When refetch() is called by the component, we
// trigger a React re-render so `useRequisition` is called again — this time
// with the success response.

import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';

// --- fake role data ---------------------------------------------------------

const FAKE_ROLE = {
  id: 'role-abc',
  role_title: 'Senior Engineer',
  role_location: 'Remote',
  department: 'Engineering',
  created_by_name: 'Jane Recruiter',
  status: 'planned' as 'planned' | 'intake_pending' | 'closed',
};

// --- per-test state controlled by test cases --------------------------------

let renderCount = 0;
// Stores the latest forceUpdate fn from the wrapper component.
// The mock refetch calls this to simulate a real refetch completing.
let notifyRefetch: (() => void) | null = null;

// Per-test scenario
interface Scenario {
  firstError: Error | null;
  secondData: typeof FAKE_ROLE | null;
}

let scenario: Scenario = {
  firstError: new Error('session not ready'),
  secondData: FAKE_ROLE,
};

mock.module('@/hooks/use-services', () => ({
  useRequisition: (_id: string | null | undefined) => {
    renderCount += 1;
    const isFirstRender = renderCount === 1;

    if (isFirstRender && scenario.firstError) {
      return {
        data: null,
        loading: false,
        error: scenario.firstError,
        refetch: () => {
          // Calling refetch in the real hook triggers setState inside useAsyncList,
          // which causes a re-render. Simulate that by calling notifyRefetch.
          if (notifyRefetch) notifyRefetch();
        },
      };
    }

    return {
      data: scenario.secondData,
      loading: false,
      error: scenario.secondData ? null : new Error('not found'),
      refetch: () => {},
    };
  },
  useEnsureSeeded: () => {},
}));

// --- mock next/link ---------------------------------------------------------

mock.module('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

// --- mock next/navigation (controllable searchParams) -----------------------
// RoleDetailPage now reads `useSearchParams().get('debrief')` to default the
// active tab. We drive that param per-test via a module-level URLSearchParams.
let searchParamsValue = new URLSearchParams();

mock.module('next/navigation', () => ({
  useRouter: () => ({
    push: () => {},
    replace: () => {},
    back: () => {},
    forward: () => {},
    refresh: () => {},
    prefetch: () => {},
  }),
  usePathname: () => '/',
  useSearchParams: () => searchParamsValue,
}));

// --- mock heavy sub-components ----------------------------------------------

mock.module('@/components/packet-drawer/drawer', () => ({
  PacketDrawer: () => null,
}));

mock.module('./pipeline-tab', () => ({
  PipelineTab: () => <div data-testid="pipeline-tab" />,
}));

mock.module('./plan-tab', () => ({
  PlanTab: () => <div data-testid="plan-tab" />,
}));

// This stubs the whole `debrief-tab` module process-wide (bun's mock.module is
// process-wide + last-writer-wins). debrief-tab.test.tsx reads the GENUINE
// `PacketCard` via the `__REAL_DEBRIEF_TAB__` snapshot in test-setup, so this
// stub doesn't strand that suite (mirrors the plan-tab arrangement).
mock.module('./debrief-tab', () => ({
  DebriefTab: () => <div data-testid="debrief-tab" />,
}));

mock.module('./add-candidates-menu', () => ({
  AddCandidatesMenu: () => <div data-testid="add-candidates-menu" />,
}));

mock.module('./add-candidate-form', () => ({
  AddCandidateForm: () => null,
}));

// NOTE: We deliberately DO NOT `mock.module('@/services', ...)` here.
// bun's `mock.module` is process-wide and can't be restored — earlier
// versions of this file replaced `@/services` with a stub object, which
// silently broke every later test that did `import { x } from
// '@/services'`. The real services are mock-db backed and per-test
// isolated via beforeEach/afterEach in the consuming tests, so we just
// let RoleDetailPage call the real `requisitions.setStatus`.

// IMPORTANT: ServiceError must call super(message) so that `error.message`
// (and therefore `.toThrow(/pattern/)`) work in any test that runs in the
// same bun process. bun shares module registry across files; a stub class
// that omits super(message) silently broke 33 later assertions when this
// file ran first. The mock here exists only so tests don't have to set up
// the real module's DEFAULT_STATUS map — behaviour must match the real
// constructor for the test matchers downstream of it.
mock.module('@/services/service-error', () => ({
  ServiceError: class ServiceError extends Error {
    code: string;
    httpStatus: number;
    constructor(code: string, message: string, opts: { httpStatus?: number } = {}) {
      super(message);
      this.name = 'ServiceError';
      this.code = code;
      this.httpStatus = opts.httpStatus ?? 500;
    }
  },
}));

// Import AFTER mocks are registered
const { RoleDetailPage } = await import('./role-detail-page');
const { ToastProvider } = await import('@/components/ui/toast');

// ---------------------------------------------------------------------------
// Wrapper: holds a counter in state. Bumping it causes RoleDetailPage to
// re-render (NOT remount — no key change), so refs survive.
//
// notifyRefetch is a module-level test hook (not React state), so assigning
// it during render is intentional here. setTick is referentially stable
// (React guarantee), so the closure never goes stale.
// ---------------------------------------------------------------------------

function Wrapper({ roleId }: { roleId: string }) {
  const [_tick, setTick] = useState(0);
  // Assign on every render — setTick is stable so the closure is always fresh.
  // This is a test-only pattern; production components must not write to
  // module globals during render.
  notifyRefetch = () => setTick((n) => n + 1);
  // ToastProvider mirrors the (shell) layout — QuickActions consumes useToast.
  return (
    <ToastProvider>
      <RoleDetailPage id="rdp-test" roleId={roleId} />
    </ToastProvider>
  );
}

// ---------------------------------------------------------------------------

afterEach(() => {
  cleanup();
});

describe('RoleDetailPage - one-shot retry on transient error', () => {
  // Reset all module globals together before each test so callers don't have
  // to remember which globals they need to touch.
  beforeEach(() => {
    renderCount = 0;
    notifyRefetch = null;
    scenario = { firstError: new Error('session not ready'), secondData: FAKE_ROLE };
    searchParamsValue = new URLSearchParams();
  });

  test('shows role title after retry when first call errors and second succeeds', async () => {
    render(<Wrapper roleId="role-abc" />);

    // After ~300 ms the component retries; second hook call returns FAKE_ROLE
    await waitFor(
      () => {
        expect(screen.getByText('Senior Engineer')).toBeTruthy();
      },
      { timeout: 2000 },
    );

    // "Role not found" must never appear
    expect(screen.queryByText('Role not found')).toBeNull();
  });

  test('shows "Role not found" when both first and second calls error', async () => {
    scenario = { firstError: new Error('session not ready'), secondData: null };

    render(<Wrapper roleId="role-xyz" />);

    await waitFor(
      () => {
        expect(screen.getByText('Role not found')).toBeTruthy();
      },
      { timeout: 2000 },
    );

    expect(screen.queryByText('Senior Engineer')).toBeNull();
  });

  test('shows loader (not "Role not found") while retry window is pending', async () => {
    // The retry timer is RETRY_DELAY_MS (300 ms). This test asserts that during
    // that window the component shows the loader rather than "Role not found".
    //
    // We assert immediately after mount (< 300 ms) so the timer hasn't fired yet.
    // At that point retryState is 'idle' with error+no role, which showLoader maps
    // to true. Once the effect runs it transitions to 'pending', also showing loader.
    // Both states must hide "Role not found" — that's the contract we're locking in.
    render(<Wrapper roleId="role-pending" />);

    // Check right after mount — retry window has not elapsed yet. The loader is
    // the content-shaped RoleDetailSkeleton (emits .mz-skeleton cells), not the
    // old "Loading role…" text.
    await waitFor(
      () => {
        expect(document.querySelector('.mz-skeleton')).toBeTruthy();
      },
      { timeout: 250 }, // strictly less than RETRY_DELAY_MS (300 ms)
    );

    expect(screen.queryByText('Role not found')).toBeNull();
  });
});

describe('RoleDetailPage - Debrief tab un-gated (Task 3.2)', () => {
  beforeEach(() => {
    renderCount = 0;
    notifyRefetch = null;
    // No first-render error — the role resolves immediately so we render tabs.
    scenario = { firstError: null, secondData: FAKE_ROLE };
    searchParamsValue = new URLSearchParams();
  });

  test('the Debrief tab is enabled (no "Coming soon", not disabled)', async () => {
    render(<Wrapper roleId="role-abc" />);
    await waitFor(() => {
      expect(screen.getByText('Senior Engineer')).toBeTruthy();
    });

    const debriefTab = document.getElementById('rdp-test-tab-debrief') as HTMLButtonElement | null;
    expect(debriefTab).not.toBeNull();
    expect(debriefTab?.disabled).toBe(false);
    expect(debriefTab?.getAttribute('title')).toBeNull();
    // The "Coming soon" badge is gone from the tab.
    expect(screen.queryByText('Coming soon')).toBeNull();
    // Default landing tab is Pipeline (no ?debrief=).
    expect(screen.getByTestId('pipeline-tab')).toBeTruthy();
    expect(screen.queryByTestId('debrief-tab')).toBeNull();
  });

  test('clicking the Debrief tab mounts the DebriefTab', async () => {
    render(<Wrapper roleId="role-abc" />);
    await waitFor(() => {
      expect(screen.getByText('Senior Engineer')).toBeTruthy();
    });

    const debriefTab = document.getElementById('rdp-test-tab-debrief') as HTMLButtonElement;
    fireEvent.click(debriefTab);

    await waitFor(() => {
      expect(screen.getByTestId('debrief-tab')).toBeTruthy();
    });
    expect(screen.queryByTestId('pipeline-tab')).toBeNull();
  });

  test('with ?debrief=<id> the page selects + mounts the Debrief tab on mount', async () => {
    searchParamsValue = new URLSearchParams('debrief=pkt-123');
    render(<Wrapper roleId="role-abc" />);

    await waitFor(() => {
      expect(screen.getByTestId('debrief-tab')).toBeTruthy();
    });
    expect(screen.queryByTestId('pipeline-tab')).toBeNull();
    const debriefTab = document.getElementById('rdp-test-tab-debrief') as HTMLButtonElement;
    expect(debriefTab?.getAttribute('aria-selected')).toBe('true');
  });
});

describe('RoleDetailPage - status-gated header actions (migration 127 UX)', () => {
  beforeEach(() => {
    renderCount = 0;
    notifyRefetch = null;
    searchParamsValue = new URLSearchParams();
  });

  test('intake_pending: Complete intake CTA, no Publish, no Add candidates', async () => {
    scenario = {
      firstError: null,
      secondData: { ...FAKE_ROLE, status: 'intake_pending' },
    };
    render(<Wrapper roleId="role-abc" />);
    await waitFor(() => {
      expect(screen.getByText('Senior Engineer')).toBeTruthy();
    });

    expect(screen.getByText('Complete intake')).toBeTruthy();
    expect(screen.queryByText('Publish')).toBeNull();
    expect(screen.queryByTestId('add-candidates-menu')).toBeNull();
  });

  test('planned: Add candidates + Close available, no Complete intake', async () => {
    scenario = { firstError: null, secondData: FAKE_ROLE };
    render(<Wrapper roleId="role-abc" />);
    await waitFor(() => {
      expect(screen.getByText('Senior Engineer')).toBeTruthy();
    });

    expect(screen.getByTestId('add-candidates-menu')).toBeTruthy();
    expect(screen.getByText('Close')).toBeTruthy();
    expect(screen.queryByText('Complete intake')).toBeNull();
  });

  test('closed: only Reopen — no Add candidates, no Complete intake', async () => {
    scenario = {
      firstError: null,
      secondData: { ...FAKE_ROLE, status: 'closed' },
    };
    render(<Wrapper roleId="role-abc" />);
    await waitFor(() => {
      expect(screen.getByText('Senior Engineer')).toBeTruthy();
    });

    expect(screen.getByText('Reopen')).toBeTruthy();
    expect(screen.queryByTestId('add-candidates-menu')).toBeNull();
    expect(screen.queryByText('Complete intake')).toBeNull();
    expect(screen.queryByText('Close')).toBeNull();
  });
});
