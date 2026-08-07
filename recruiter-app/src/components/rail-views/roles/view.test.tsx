/**
 * RolesView — FE-J2 correctness + a11y.
 *
 * Covers the audit findings:
 *  1. Search is server-side: typing a query calls `requisitions.list` with `q`,
 *     and a match that lives on page 2+ (NOT in the first page slice) renders.
 *     The old in-memory page-slice filter is gone.
 *  2. Kebab a11y: opens, closes on Escape + outside-click, focus moves in.
 *  3. Tabs a11y: the active tabpanel is associated via aria-controls /
 *     aria-labelledby and tabs use roving tabindex.
 *
 * Strategy: spy on the REAL services so the genuine `useRequisitions` hooks
 * run, letting us assert the exact `list(status, { q })` calls the wiring
 * makes — a non-polluting service-spy pattern.
 */

import { afterEach, describe, expect, spyOn, test } from 'bun:test';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { ToastProvider } from '@/components/ui/toast';
import { clearAsyncCache } from '@/hooks/use-services';
import * as services from '@/services';
import type { RoleListItem, RoleListPage } from '@/services/requisitions';
import { RolesView } from './view';

afterEach(() => {
  cleanup();
  // The SWR cache in useAsyncList is module-level and persists across tests in
  // this process; clear it so the cold-load test sees an empty cache (prior
  // data-resolving tests would otherwise warm-seed its hooks).
  clearAsyncCache();
});

function role(id: string, title: string, status: RoleListItem['status'] = 'planned'): RoleListItem {
  return {
    id,
    role_title: title,
    role_location: 'Remote',
    department: 'Engineering',
    created_by_name: 'Jane Recruiter',
    status,
    created_at: new Date().toISOString(),
    rounds: [],
    pipeline: { candidate_count: 1, round_count: 2 },
  } as unknown as RoleListItem;
}

function page(items: RoleListItem[], total = items.length): RoleListPage {
  return {
    items,
    page: 1,
    page_size: 10,
    total,
    status_counts: { open: total, pending: 0, closed: 0 },
  };
}

describe('RolesView — server-side search (FE-J2)', () => {
  test('typing a query calls requisitions.list with q and renders a match not on page 1', async () => {
    const FIRST_PAGE = page([role('r1', 'Frontend Engineer')], 25);
    // The match lives beyond page 1 — only reachable via server-side q.
    const Q_PAGE = page([role('r99', 'Staff Platform Engineer')], 1);

    const listSpy = spyOn(services.requisitions, 'list').mockImplementation((_status, options) => {
      return Promise.resolve(options?.q ? Q_PAGE : FIRST_PAGE);
    });

    const { container } = render(
      <ToastProvider>
        <RolesView id="roles" />
      </ToastProvider>,
    );

    await waitFor(() => {
      expect(container.querySelector('#roles-table')).not.toBeNull();
    });
    // Page-1-only role is shown before searching.
    expect(container.textContent).toContain('Frontend Engineer');
    expect(container.textContent).not.toContain('Staff Platform Engineer');

    const input = container.querySelector('#roles-search-input') as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: 'platform' } });
    });

    // The server-side q-fetch returns the page-2 match and it renders.
    await waitFor(() => {
      expect(container.textContent).toContain('Staff Platform Engineer');
    });

    // The active tab's list() was called with the query (q), proving the
    // search hit the server rather than slicing the loaded page in memory.
    const calledWithQ = listSpy.mock.calls.some(
      ([status, opts]) => status === 'planned' && opts?.q === 'platform',
    );
    expect(calledWithQ).toBe(true);

    listSpy.mockRestore();
  });
});

describe('RolesView — kebab a11y (FE-J2)', () => {
  test('kebab opens, moves focus into the menu, and closes on Escape + outside-click', async () => {
    const listSpy = spyOn(services.requisitions, 'list').mockResolvedValue(
      page([role('r1', 'Frontend Engineer')], 1),
    );

    const { container } = render(
      <ToastProvider>
        <RolesView id="roles" />
      </ToastProvider>,
    );

    await waitFor(() => {
      expect(container.querySelector('#roles-row-r1-kebab')).not.toBeNull();
    });

    const kebab = container.querySelector('#roles-row-r1-kebab') as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(kebab);
    });

    // Menu open + focus moved into it.
    await waitFor(() => {
      expect(container.querySelector('#roles-row-r1-kebab-menu')).not.toBeNull();
    });
    const menu = container.querySelector('#roles-row-r1-kebab-menu') as HTMLElement;
    expect(menu.contains(document.activeElement)).toBe(true);

    // Escape closes it.
    await act(async () => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });
    await waitFor(() => {
      expect(container.querySelector('#roles-row-r1-kebab-menu')).toBeNull();
    });

    // Re-open, then outside-click closes it.
    await act(async () => {
      fireEvent.click(kebab);
    });
    await waitFor(() => {
      expect(container.querySelector('#roles-row-r1-kebab-menu')).not.toBeNull();
    });
    await act(async () => {
      fireEvent.mouseDown(document.body);
    });
    await waitFor(() => {
      expect(container.querySelector('#roles-row-r1-kebab-menu')).toBeNull();
    });

    listSpy.mockRestore();
  });
});

describe('RolesView — cold-load skeleton', () => {
  test('shows the table skeleton while the active tab has no data yet', () => {
    const listSpy = spyOn(services.requisitions, 'list').mockReturnValue(
      new Promise<RoleListPage>(() => {}),
    );

    const { container } = render(
      <ToastProvider>
        <RolesView id="roles" />
      </ToastProvider>,
    );
    // Cold load → content-shaped skeleton, NOT the empty-state flash.
    expect(container.querySelector('#roles-skeleton')).not.toBeNull();
    expect(container.querySelector('#roles-empty')).toBeNull();

    listSpy.mockRestore();
  });
});

describe('RolesView — tabs a11y (FE-J2)', () => {
  test('active tabpanel is associated via aria-controls / aria-labelledby and tabs use roving tabindex', async () => {
    const listSpy = spyOn(services.requisitions, 'list').mockResolvedValue(
      page([role('r1', 'Frontend Engineer')], 1),
    );

    const { container } = render(
      <ToastProvider>
        <RolesView id="roles" />
      </ToastProvider>,
    );

    await waitFor(() => {
      expect(container.querySelector('#roles-table')).not.toBeNull();
    });

    const openTab = container.querySelector('#roles-tab-open') as HTMLButtonElement;
    const panelId = openTab.getAttribute('aria-controls');
    expect(panelId).toBeTruthy();

    const panel = document.getElementById(panelId as string);
    expect(panel).not.toBeNull();
    expect(panel?.getAttribute('role')).toBe('tabpanel');
    expect(panel?.getAttribute('aria-labelledby')).toBe(openTab.id);

    // Roving tabindex: active tab is 0, the rest are -1.
    expect(openTab.getAttribute('tabindex')).toBe('0');
    const pendingTab = container.querySelector('#roles-tab-pending') as HTMLButtonElement;
    expect(pendingTab.getAttribute('tabindex')).toBe('-1');

    // ArrowRight moves focus to the next tab.
    openTab.focus();
    await act(async () => {
      fireEvent.keyDown(openTab, { key: 'ArrowRight' });
    });
    expect(document.activeElement).toBe(pendingTab);

    listSpy.mockRestore();
  });
});
