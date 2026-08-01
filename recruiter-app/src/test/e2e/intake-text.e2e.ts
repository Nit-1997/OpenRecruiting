import { expect, test } from '@playwright/test';

/**
 * Phase 3 — Task 14: text path e2e.
 *
 * Mirrors the structure of Phase 2's intake-voice.e2e.ts. All tests are
 * gated on E2E_TEST_USER_EMAIL/PASSWORD and skipped when unset.
 *
 * The full happy-path / coverage-update / send-while-streaming / end-chat /
 * browser-close specs are marked `test.skip(true, 'pending fixture seeding')`
 * because the staging fixture-seeding infrastructure is not yet in place —
 * same approach as Phase 2 I1. Locators below are anchored to the real
 * Phase 1 + Phase 3 components and ready to un-skip the moment fixture
 * seeding lands.
 *
 *   Phase 1 form     — `#intake-page-canvas-stage-intake-form-*`
 *   Phase 1 ready    — `#intake-session-page-canvas-stage-ready-start-chat`
 *   Phase 3 chat     — `#v2-intake-text-chat-panel`,
 *                      `#v2-intake-text-composer-input`,
 *                      `#v2-intake-text-composer-send`,
 *                      `#v2-intake-text-message-{idx}`,
 *                      `#v2-intake-text-message-streaming-content`
 *   Phase 3 end-chat — `#v2-intake-end-chat-button`
 *   Wrapping stage   — `[data-testid="v2-intake-stage-wrapping"]`
 */

const EMAIL = process.env.E2E_TEST_USER_EMAIL ?? '';
const PASSWORD = process.env.E2E_TEST_USER_PASSWORD ?? '';

test.describe('Phase 3 — intake text path', () => {
  test.skip(!EMAIL || !PASSWORD, 'E2E credentials not configured');

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('#login-email').fill(EMAIL);
    await page.locator('#login-password').fill(PASSWORD);
    await page.locator('#login-submit').click();
    await expect(page).toHaveURL(/\/(home|intake|roles)/, { timeout: 10_000 });
  });

  test('chat happy path: form → ready → start chat → send → assistant reply', async ({ page }) => {
    test.skip(true, 'pending staging-fixture seeding helpers');

    await page.goto('/intake');
    await page.locator('#intake-page-history-new-intake').click();
    await page
      .locator('#intake-page-canvas-stage-intake-form-role-name')
      .fill('Senior FE Engineer');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-min').fill('4');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-max').fill('8');
    await page.locator('#intake-page-canvas-stage-intake-form-location').fill('Remote');
    await page.locator('#intake-page-canvas-stage-intake-form-submit').click();

    // Wait for ready stage
    await expect(page.locator('#intake-session-page-canvas-stage-ready')).toBeVisible({
      timeout: 60_000,
    });

    // Start with chat
    await page.locator('#intake-session-page-canvas-stage-ready-start-chat').click();
    await expect(page.locator('#v2-intake-text-chat-panel')).toBeVisible();

    // Send first message
    const composer = page.locator('#v2-intake-text-composer-input');
    await composer.fill('hi, ready to chat about the role');
    await page.locator('#v2-intake-text-composer-send').click();

    // First token within 1.5s
    await expect(page.locator('#v2-intake-text-message-streaming-content')).toBeVisible({
      timeout: 1500,
    });

    // Composer disabled during stream
    await expect(page.locator('#v2-intake-text-composer-send')).toBeDisabled();

    // Stream finishes — assistant turn appears, streaming bubble gone
    await expect(page.locator('#v2-intake-text-message-1')).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('#v2-intake-text-message-streaming-content')).toBeHidden();
    await expect(page.locator('#v2-intake-text-composer-send')).toBeEnabled();
  });

  test('coverage table updates from tool calls', async ({ page }) => {
    test.skip(true, 'pending staging-fixture seeding helpers');

    // Seeds a chat session, sends a message mentioning Python + Postgres,
    // expects the q4_must_haves coverage row to contain "python" or "postgres"
    // after the assistant's tool call resolves.
    await page.goto('/intake');
    await page.locator('#intake-page-history-new-intake').click();
    await page
      .locator('#intake-page-canvas-stage-intake-form-role-name')
      .fill('Backend Engineer');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-min').fill('3');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-max').fill('7');
    await page.locator('#intake-page-canvas-stage-intake-form-location').fill('Remote');
    await page.locator('#intake-page-canvas-stage-intake-form-submit').click();

    await expect(page.locator('#intake-session-page-canvas-stage-ready')).toBeVisible({
      timeout: 60_000,
    });
    await page.locator('#intake-session-page-canvas-stage-ready-start-chat').click();
    await expect(page.locator('#v2-intake-text-chat-panel')).toBeVisible();

    await page
      .locator('#v2-intake-text-composer-input')
      .fill('Must-haves are Python 3.11 and Postgres 15. asyncio expertise required.');
    await page.locator('#v2-intake-text-composer-send').click();

    // Wait for stream to settle
    await expect(page.locator('#v2-intake-text-message-1')).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('#v2-intake-text-message-streaming-content')).toBeHidden();

    const mustHaves = page.getByTestId('v2-intake-coverage-text-q4_must_haves');
    await expect(mustHaves).toContainText(/python|postgres/i, { timeout: 10_000 });
  });

  test('send while in flight is rejected', async ({ page }) => {
    test.skip(true, 'pending staging-fixture seeding helpers');

    await page.goto('/intake');
    await page.locator('#intake-page-history-new-intake').click();
    await page
      .locator('#intake-page-canvas-stage-intake-form-role-name')
      .fill('In-Flight Role');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-min').fill('2');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-max').fill('5');
    await page.locator('#intake-page-canvas-stage-intake-form-location').fill('Remote');
    await page.locator('#intake-page-canvas-stage-intake-form-submit').click();

    await expect(page.locator('#intake-session-page-canvas-stage-ready')).toBeVisible({
      timeout: 60_000,
    });
    await page.locator('#intake-session-page-canvas-stage-ready-start-chat').click();
    await expect(page.locator('#v2-intake-text-chat-panel')).toBeVisible();

    await page.locator('#v2-intake-text-composer-input').fill('first message');
    await page.locator('#v2-intake-text-composer-send').click();

    // While the stream is in flight, both the send button and input must be disabled
    await expect(page.locator('#v2-intake-text-message-streaming-content')).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.locator('#v2-intake-text-composer-send')).toBeDisabled();
    await expect(page.locator('#v2-intake-text-composer-input')).toBeDisabled();
  });

  test('end chat clears active_modality and flips to wrapping', async ({ page }) => {
    test.skip(true, 'pending staging-fixture seeding helpers');

    await page.goto('/intake');
    await page.locator('#intake-page-history-new-intake').click();
    await page
      .locator('#intake-page-canvas-stage-intake-form-role-name')
      .fill('End Chat Role');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-min').fill('3');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-max').fill('6');
    await page.locator('#intake-page-canvas-stage-intake-form-location').fill('Remote');
    await page.locator('#intake-page-canvas-stage-intake-form-submit').click();

    await expect(page.locator('#intake-session-page-canvas-stage-ready')).toBeVisible({
      timeout: 60_000,
    });
    await page.locator('#intake-session-page-canvas-stage-ready-start-chat').click();
    await expect(page.locator('#v2-intake-text-chat-panel')).toBeVisible();

    await page.locator('#v2-intake-text-composer-input').fill('quick chat then end');
    await page.locator('#v2-intake-text-composer-send').click();
    await expect(page.locator('#v2-intake-text-message-1')).toBeVisible({ timeout: 30_000 });

    // End-chat now opens the accessible ConfirmDialog (not window.confirm);
    // click its confirm action to proceed.
    await page.locator('#v2-intake-end-chat-button').click();
    await page.locator('#confirm-dialog-confirm').click();

    await expect(page.getByTestId('v2-intake-stage-wrapping')).toBeVisible({ timeout: 10_000 });
  });

  test('browser-close mid-stream — reload shows no orphaned streaming bubble', async ({
    page,
    context,
  }) => {
    test.skip(true, 'pending staging-fixture seeding helpers');

    await page.goto('/intake');
    await page.locator('#intake-page-history-new-intake').click();
    await page
      .locator('#intake-page-canvas-stage-intake-form-role-name')
      .fill('Browser Close Role');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-min').fill('2');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-max').fill('5');
    await page.locator('#intake-page-canvas-stage-intake-form-location').fill('Remote');
    await page.locator('#intake-page-canvas-stage-intake-form-submit').click();

    await expect(page.locator('#intake-session-page-canvas-stage-ready')).toBeVisible({
      timeout: 60_000,
    });
    await page.locator('#intake-session-page-canvas-stage-ready-start-chat').click();
    await expect(page.locator('#v2-intake-text-chat-panel')).toBeVisible();

    const sessionUrl = page.url();

    await page
      .locator('#v2-intake-text-composer-input')
      .fill('long message that will still be streaming when we close');
    await page.locator('#v2-intake-text-composer-send').click();
    await expect(page.locator('#v2-intake-text-message-streaming-content')).toBeVisible({
      timeout: 5_000,
    });

    // Close the tab mid-stream
    await page.close();

    // Re-open the session — no orphaned streaming bubble should appear
    const fresh = await context.newPage();
    await fresh.goto(sessionUrl);
    await expect(fresh.locator('#v2-intake-text-chat-panel')).toBeVisible({ timeout: 10_000 });
    await expect(fresh.locator('#v2-intake-text-message-streaming-content')).toHaveCount(0);
  });
});
