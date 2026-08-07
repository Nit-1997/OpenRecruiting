/**
 * FE-T2 — Automated accessibility gate (axe-core).
 *
 * Locks in the a11y work from FE-F2 (Dialog/ConfirmDialog/Toast/Label/focus-trap),
 * FE-J2 (roles tabs + kebab) and FE-J4 (ConfirmDialog adoption) by running
 * axe-core against the rendered DOM and failing the test on any serious/critical
 * violation. Because these tests live in the normal `bun test` suite, CI (which
 * already runs `bun test`) enforces the gate with no extra workflow step.
 *
 * Scope of the gate
 * -----------------
 * We assert NO violations of `serious` or `critical` impact. `minor`/`moderate`
 * findings are not asserted on (yet) — happy-dom has no layout/contrast engine so
 * colour-contrast (`moderate`/`serious`-by-rule) and several `region`/`landmark`
 * (`moderate`) rules either can't run or fire spuriously on isolated component
 * fragments rendered without a `<main>` wrapper. We scope the run to the rendered
 * subtree and exclude colour-contrast (cannot be evaluated in happy-dom) so the
 * gate is deterministic. Every filtered category is documented at `AXE_RUN_OPTIONS`.
 *
 * What's covered: shared Dialog (open), ConfirmDialog, Toast, a Label+input pair,
 * the Input primitive, and the roles rail (tabs + kebab — FE-J2). All of these
 * pass clean today; this file is the regression fence.
 */

import { afterEach, describe, expect, spyOn, test } from 'bun:test';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import axe from 'axe-core';
import { useState } from 'react';
import { RolesView } from '@/components/rail-views/roles/view';
import { ConfirmDialogProvider, useConfirm } from '@/components/ui/confirm-dialog';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ToastProvider, useToast } from '@/components/ui/toast';
import * as services from '@/services';
import type { RoleListItem, RoleListPage } from '@/services/requisitions';

afterEach(cleanup);

// Impact levels that fail the gate. minor/moderate are observed-but-not-asserted
// for now (see file header); we ratchet up once those are clean across the app.
const FAILING_IMPACTS = new Set(['serious', 'critical']);

/**
 * axe options shared by every assertion.
 *
 * - `resultTypes: ['violations']` — we only need the failures, skips the
 *   (expensive) pass/incomplete/inapplicable bookkeeping.
 * - `color-contrast` disabled — happy-dom has no CSS layout/paint engine, so the
 *   rule can neither be evaluated reliably nor produce a real signal here. Visual
 *   contrast is owned by design-token tests + manual/Playwright review.
 * - `region` disabled — fires `moderate` "content not in a landmark" on isolated
 *   component fragments that are intentionally rendered without their page
 *   `<main>` wrapper in a unit test. It is moderate (not asserted) anyway, but we
 *   disable it so a future ratchet to `moderate` doesn't trip on test scaffolding.
 */
const AXE_RUN_OPTIONS: axe.RunOptions = {
  resultTypes: ['violations'],
  rules: {
    'color-contrast': { enabled: false },
    region: { enabled: false },
  },
};

function serialize(violations: axe.Result[]) {
  return violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    nodes: v.nodes.map((n) => n.target),
  }));
}

/**
 * Run axe against `root` and assert there are no serious/critical violations.
 * On failure the error message lists each offending rule + node so the lane
 * owner can act on it (rather than a bare "expected 0 to be 0").
 */
async function expectNoSeriousViolations(root: Element): Promise<void> {
  const results = await axe.run(root, AXE_RUN_OPTIONS);
  const failing = results.violations.filter((v) => v.impact && FAILING_IMPACTS.has(v.impact));
  if (failing.length > 0) {
    throw new Error(
      `axe found ${failing.length} serious/critical violation(s):\n${JSON.stringify(
        serialize(failing),
        null,
        2,
      )}`,
    );
  }
  expect(failing.length).toBe(0);
}

// --- Dialog ----------------------------------------------------------------

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <button id="a11y-dlg-trigger" type="button">
            Open settings
          </button>
        }
      />
      <DialogContent>
        <DialogTitle>Settings</DialogTitle>
        <DialogDescription>Edit your workspace settings.</DialogDescription>
        <button id="a11y-dlg-inside" type="button">
          Save
        </button>
      </DialogContent>
    </Dialog>
  );
}

describe('a11y: Dialog (FE-F2)', () => {
  test('open dialog has no serious/critical axe violations', async () => {
    render(<DialogHarness />);
    await act(async () => {
      fireEvent.click(document.getElementById('a11y-dlg-trigger') as HTMLElement);
    });
    await waitFor(() => {
      expect(document.querySelector('[data-slot="dialog-content"]')).toBeTruthy();
    });
    // Dialog portals outside the render container — scan the whole body.
    await expectNoSeriousViolations(document.body);
  });
});

// --- ConfirmDialog ---------------------------------------------------------

function ConfirmHarness() {
  const confirm = useConfirm();
  return (
    <button
      id="a11y-confirm-ask"
      type="button"
      onClick={() => {
        void confirm({
          title: 'Delete role?',
          body: 'This cannot be undone.',
          confirmLabel: 'Delete',
          danger: true,
        });
      }}
    >
      ask
    </button>
  );
}

describe('a11y: ConfirmDialog (FE-F2 / FE-J4)', () => {
  test('open confirm dialog has no serious/critical axe violations', async () => {
    render(
      <ConfirmDialogProvider>
        <ConfirmHarness />
      </ConfirmDialogProvider>,
    );
    await act(async () => {
      fireEvent.click(document.getElementById('a11y-confirm-ask') as HTMLElement);
    });
    await waitFor(() => {
      expect(document.querySelector('[data-slot="confirm-dialog"]')).toBeTruthy();
    });
    await expectNoSeriousViolations(document.body);
  });
});

// --- Toast -----------------------------------------------------------------

function ToastHarness() {
  const { showToast } = useToast();
  return (
    <div>
      <button
        id="a11y-toast-info"
        type="button"
        onClick={() => showToast('Saved your changes', 'info')}
      >
        info
      </button>
      <button
        id="a11y-toast-error"
        type="button"
        onClick={() => showToast('Something went wrong', 'error')}
      >
        error
      </button>
    </div>
  );
}

describe('a11y: Toast (FE-F2)', () => {
  test('live region with an info + error toast has no serious/critical axe violations', async () => {
    const { container } = render(
      <ToastProvider>
        <ToastHarness />
      </ToastProvider>,
    );
    await act(async () => {
      fireEvent.click(document.getElementById('a11y-toast-info') as HTMLElement);
      fireEvent.click(document.getElementById('a11y-toast-error') as HTMLElement);
    });
    await waitFor(() => {
      expect(document.querySelectorAll('[data-slot="toast-item"]').length).toBe(2);
    });
    await expectNoSeriousViolations(container);
  });
});

// --- Label + input ---------------------------------------------------------

describe('a11y: Label + control (FE-F2)', () => {
  test('a labelled input has no serious/critical axe violations', async () => {
    const { container } = render(
      <form id="a11y-label-form">
        <Label id="a11y-email-label" htmlFor="a11y-email-input">
          Email
        </Label>
        <Input id="a11y-email-input" type="email" placeholder="you@example.com" />
      </form>,
    );
    await expectNoSeriousViolations(container);
  });
});

// --- Roles rail (tabs + kebab) — FE-J2 -------------------------------------

function roleItem(
  id: string,
  title: string,
  status: RoleListItem['status'] = 'planned',
): RoleListItem {
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

function rolePage(items: RoleListItem[], total = items.length): RoleListPage {
  return {
    items,
    page: 1,
    page_size: 10,
    total,
    status_counts: { open: total, pending: 0, closed: 0 },
  };
}

describe('a11y: RolesView tabs + kebab (FE-J2)', () => {
  test('roles rail (tabs visible) has no serious/critical axe violations', async () => {
    const listSpy = spyOn(services.requisitions, 'list').mockResolvedValue(
      rolePage([roleItem('r1', 'Frontend Engineer')], 1),
    );

    const { container } = render(
      <ToastProvider>
        <RolesView id="a11y-roles" />
      </ToastProvider>,
    );

    await waitFor(() => {
      expect(container.querySelector('#a11y-roles-table')).not.toBeNull();
    });

    await expectNoSeriousViolations(container);

    listSpy.mockRestore();
  });

  test('roles rail with an open kebab menu has no serious/critical axe violations', async () => {
    const listSpy = spyOn(services.requisitions, 'list').mockResolvedValue(
      rolePage([roleItem('r1', 'Frontend Engineer')], 1),
    );

    const { container } = render(
      <ToastProvider>
        <RolesView id="a11y-roles" />
      </ToastProvider>,
    );

    await waitFor(() => {
      expect(container.querySelector('#a11y-roles-row-r1-kebab')).not.toBeNull();
    });

    await act(async () => {
      fireEvent.click(container.querySelector('#a11y-roles-row-r1-kebab') as HTMLElement);
    });
    await waitFor(() => {
      expect(container.querySelector('#a11y-roles-row-r1-kebab-menu')).not.toBeNull();
    });

    // Kebab menu may portal — scan the whole body.
    await expectNoSeriousViolations(document.body);

    listSpy.mockRestore();
  });
});
