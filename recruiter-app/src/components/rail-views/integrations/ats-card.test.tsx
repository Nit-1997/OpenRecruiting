import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { ConfirmDialogProvider } from '@/components/ui/confirm-dialog';
import { ToastProvider } from '@/components/ui/toast';
import type { AtsStatus } from '@/services/integrations-ats';

// Mock one layer deeper than the component (the service module), NOT
// v2-client/fetch: other test files corrupt @/lib/v2-client process-wide via
// mock.module (auth-store.test.ts), so depending on the real HTTP chain makes
// these tests order-sensitive. Spread ...actual so the module stays intact
// for every other consumer (CLAUDE.md bun testing rules).
const actual = await import('@/services/integrations-ats');

let statusHandler: () => Promise<AtsStatus>;
let sessionHandler: () => Promise<string>;
let completeHandler: (details: unknown) => Promise<AtsStatus>;
let disconnectHandler: () => Promise<void>;

mock.module('@/services/integrations-ats', () => ({
  ...actual,
  getAtsStatus: () => statusHandler(),
  getAtsSessionToken: () => sessionHandler(),
  completeAtsConnection: (details: unknown) => completeHandler(details),
  disconnectAts: () => disconnectHandler(),
}));

const { AtsCard } = await import('./ats-card');

const NOT_CONNECTED: AtsStatus = {
  connected: false,
  provider: null,
  status: null,
  connected_at: null,
  connected_by_name: null,
};

const CONNECTED: AtsStatus = {
  connected: true,
  provider: 'workable',
  status: 'active',
  connected_at: '2026-06-11T00:00:00Z',
  connected_by_name: 'Rae',
};

function notFoundError(): Error & { code: string } {
  return Object.assign(new Error('ATS integrations are not enabled'), {
    code: 'not_found',
  });
}

function renderCard() {
  return render(
    <ToastProvider>
      <ConfirmDialogProvider>
        <AtsCard id="ats-card" />
      </ConfirmDialogProvider>
    </ToastProvider>,
  );
}

describe('AtsCard', () => {
  beforeEach(() => {
    statusHandler = async () => NOT_CONNECTED;
    sessionHandler = async () => 'tok';
    completeHandler = async () => CONNECTED;
    disconnectHandler = async () => undefined;
  });

  afterEach(() => {
    cleanup();
  });

  test('renders not-connected state with knit-auth trigger', async () => {
    const { container } = renderCard();
    await waitFor(() => {
      expect(screen.getByText('Not connected')).toBeTruthy();
    });
    expect(container.querySelector('knit-auth')).toBeTruthy();
    expect(document.getElementById('ats-card-connect')).toBeTruthy();
  });

  test('prefetches a session token onto the knit-auth element', async () => {
    const { container } = renderCard();
    await waitFor(() => {
      expect(
        container.querySelector('knit-auth')?.getAttribute('authsessiontoken'),
      ).toBe('tok');
    });
  });

  test('onFinish completes the connection and flips to connected', async () => {
    const completed: unknown[] = [];
    completeHandler = async (details) => {
      completed.push(details);
      return CONNECTED;
    };

    const { container } = renderCard();
    await waitFor(() => {
      expect(container.querySelector('knit-auth')).toBeTruthy();
    });

    const node = container.querySelector('knit-auth') as HTMLElement;
    act(() => {
      node.dispatchEvent(
        new CustomEvent('onFinish', {
          detail: {
            integrationDetails: {
              integrationId: 'int-1',
              appId: 'workable',
              categoryId: 'ATS',
              originOrgId: 'org-1',
              success: true,
            },
          },
        }),
      );
    });

    await waitFor(() => {
      expect(screen.getByText('Workable')).toBeTruthy();
    });
    expect(document.getElementById('ats-card-badge')?.textContent).toContain('Connected');
    expect((completed[0] as { integrationId: string }).integrationId).toBe('int-1');
  });

  test('not_found status renders the coming-soon state without a connect button', async () => {
    statusHandler = async () => {
      throw notFoundError();
    };
    renderCard();
    await waitFor(() => {
      expect(screen.getByText('Coming soon')).toBeTruthy();
    });
    expect(document.getElementById('ats-card-connect')).toBeFalsy();
  });
});
