import { expect, test } from '@playwright/test';

/**
 * Phase 2 — Task I1: voice path e2e.
 *
 * Chrome launch flags `--use-fake-device-for-media-stream` +
 * `--use-fake-ui-for-media-stream` (configured in playwright.config.ts)
 * auto-grant the microphone and feed a synthetic audio device, so the
 * voice path can run headless without prompting the user.
 *
 * Test-ids below are anchored to the real Phase 1 + Phase 2 components:
 *   Phase 1 form  — `#intake-page-canvas-stage-intake-form-*`
 *   Phase 1 ready — `#intake-session-page-canvas-stage-ready-start-voice`
 *   Phase 2 voice — `data-testid="v2-intake-voice-panel-*"`,
 *                   `data-testid="v2-intake-transcript-*"`,
 *                   `data-testid="v2-intake-coverage-*"`,
 *                   `data-testid="v2-intake-editor-*"`,
 *                   `data-testid="v2-intake-stage-voice-active"`,
 *                   `data-testid="v2-intake-stage-wrapping"`,
 *                   `data-testid="v2-intake-voice-reconnect-*"`.
 *
 * Cascade deferred: Phase 1's `ready-start-voice` button is disabled
 * (Phase 1 Task 17 stub). Phase 2 product work needs to enable it +
 * set the pendingTransition to `voice_active`. That's not in this
 * test-only task. The click-driven flows below are written against the
 * real ids and ready to un-skip the moment the button gets wired.
 */

const EMAIL = process.env.E2E_TEST_USER_EMAIL ?? '';
const PASSWORD = process.env.E2E_TEST_USER_PASSWORD ?? '';

test.describe('Phase 2 — intake voice path', () => {
  test.skip(!EMAIL || !PASSWORD, 'E2E credentials not configured');

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('#login-email').fill(EMAIL);
    await page.locator('#login-password').fill(PASSWORD);
    await page.locator('#login-submit').click();
    await expect(page).toHaveURL(/\/(home|intake|roles)/, { timeout: 10_000 });
  });

  test('happy path: form → prefill → voice call → coverage update → wrapping', async ({ page }) => {
    test.skip(
      true,
      'cascade: ready-start-voice button still disabled in Phase 1 stub — un-skip once Phase 2 wires the click',
    );

    await page.goto('/intake');
    await expect(page.locator('#intake-page-history')).toBeVisible({ timeout: 10_000 });
    await page.locator('#intake-page-history-new-intake').click();

    await page
      .locator('#intake-page-canvas-stage-intake-form-role-name')
      .fill('Staff Backend Engineer');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-min').fill('5');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-max').fill('9');
    await page.locator('#intake-page-canvas-stage-intake-form-location').fill('San Francisco');
    await page.locator('#intake-page-canvas-stage-intake-form-submit').click();

    await expect(page.locator('#intake-session-page-canvas-stage-ready')).toBeVisible({
      timeout: 60_000,
    });

    await page.locator('#intake-session-page-canvas-stage-ready-start-voice').click();

    await expect(page.getByTestId('v2-intake-stage-voice-active')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('v2-intake-voice-panel-orb')).toBeVisible();

    await page.getByTestId('v2-intake-voice-panel-start-btn').click();

    await expect(page.locator('#v2-intake-voice-panel-status')).toContainText(/Live|Connecting/i, {
      timeout: 15_000,
    });

    await expect(page.getByTestId('v2-intake-transcript-turn-0')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('v2-intake-coverage-table')).toBeVisible();

    await page.getByTestId('v2-intake-voice-panel-hangup-btn').click();
    await expect(page.locator('#v2-intake-voice-panel-status')).toContainText(/Call ended/i);

    await expect(page.getByTestId('v2-intake-stage-wrapping')).toBeVisible({ timeout: 10_000 });
  });

  test('manual edit: coverage card → edit → save → edited pip appears', async ({ page }) => {
    test.skip(true, 'cascade: requires voice_active stage, gated on Phase 2 ready-button wiring');

    await page.goto('/intake');
    await page.locator('#intake-page-history-new-intake').click();
    await page
      .locator('#intake-page-canvas-stage-intake-form-role-name')
      .fill('Edit Coverage Role');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-min').fill('2');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-max').fill('5');
    await page.locator('#intake-page-canvas-stage-intake-form-location').fill('Remote');
    await page.locator('#intake-page-canvas-stage-intake-form-submit').click();

    await expect(page.locator('#intake-session-page-canvas-stage-ready')).toBeVisible({
      timeout: 60_000,
    });
    await page.locator('#intake-session-page-canvas-stage-ready-start-voice').click();
    await expect(page.getByTestId('v2-intake-stage-voice-active')).toBeVisible({ timeout: 10_000 });

    const qid = 'q4_must_haves';
    await page.getByTestId(`v2-intake-coverage-edit-btn-${qid}`).click();
    await expect(page.getByTestId(`v2-intake-editor-${qid}`)).toBeVisible();

    const textarea = page.getByTestId(`v2-intake-editor-textarea-${qid}`);
    await textarea.fill('Python 3.11, FastAPI, asyncio expertise required');
    await page.getByTestId(`v2-intake-editor-status-${qid}`).selectOption('validated');
    await page.getByTestId(`v2-intake-editor-save-btn-${qid}`).click();

    await expect(page.getByTestId(`v2-intake-editor-${qid}`)).toHaveCount(0, { timeout: 5_000 });
    await expect(page.getByTestId(`v2-intake-coverage-pip-${qid}`)).toBeVisible();
    await expect(page.getByTestId(`v2-intake-coverage-text-${qid}`)).toContainText(/FastAPI/);
  });

  test('reload mid-call shows voice-reconnect modal with explicit consent', async ({ page }) => {
    test.skip(
      true,
      'cascade: requires backend to persist active_modality=voice; un-skip when seedable',
    );

    await page.goto('/intake');
    await page.locator('#intake-page-history-new-intake').click();
    await page
      .locator('#intake-page-canvas-stage-intake-form-role-name')
      .fill('Reload Mid-Call Role');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-min').fill('3');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-max').fill('6');
    await page.locator('#intake-page-canvas-stage-intake-form-location').fill('NYC');
    await page.locator('#intake-page-canvas-stage-intake-form-submit').click();

    await expect(page.locator('#intake-session-page-canvas-stage-ready')).toBeVisible({
      timeout: 60_000,
    });
    await page.locator('#intake-session-page-canvas-stage-ready-start-voice').click();
    await expect(page.getByTestId('v2-intake-stage-voice-active')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('v2-intake-voice-panel-start-btn').click();
    await expect(page.locator('#v2-intake-voice-panel-status')).toContainText(/Live|Connecting/i, {
      timeout: 15_000,
    });

    await page.reload();

    await expect(page.getByTestId('v2-intake-voice-reconnect-modal')).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId('v2-intake-voice-reconnect-rejoin-btn')).toBeVisible();
    await expect(page.getByTestId('v2-intake-voice-reconnect-switch-btn')).toBeVisible();

    await page.getByTestId('v2-intake-voice-reconnect-rejoin-btn').click();
    await expect(page.getByTestId('v2-intake-stage-voice-active')).toBeVisible({ timeout: 10_000 });
  });

  test('mic denied: error banner surfaces, start button does not connect', async ({ browser }) => {
    test.skip(true, 'cascade: requires voice_active stage, gated on Phase 2 ready-button wiring');

    const context = await browser.newContext({ permissions: [] });
    const page = await context.newPage();

    await page.goto('/login');
    await page.locator('#login-email').fill(EMAIL);
    await page.locator('#login-password').fill(PASSWORD);
    await page.locator('#login-submit').click();
    await expect(page).toHaveURL(/\/(home|intake|roles)/, { timeout: 10_000 });

    await page.goto('/intake');
    await page.locator('#intake-page-history-new-intake').click();
    await page.locator('#intake-page-canvas-stage-intake-form-role-name').fill('Mic Denied Role');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-min').fill('2');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-max').fill('4');
    await page.locator('#intake-page-canvas-stage-intake-form-location').fill('Remote');
    await page.locator('#intake-page-canvas-stage-intake-form-submit').click();

    await expect(page.locator('#intake-session-page-canvas-stage-ready')).toBeVisible({
      timeout: 60_000,
    });
    await page.locator('#intake-session-page-canvas-stage-ready-start-voice').click();
    await expect(page.getByTestId('v2-intake-stage-voice-active')).toBeVisible({ timeout: 10_000 });

    await page.getByTestId('v2-intake-voice-panel-start-btn').click();

    await expect(page.getByTestId('v2-intake-voice-panel-error')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('v2-intake-voice-panel-error')).toContainText(
      /mic|permission|denied/i,
    );
    await expect(page.locator('#v2-intake-voice-panel-status')).toContainText(/Error|Ready/i);

    await context.close();
  });
});
