import { test, expect } from '@playwright/test';

const EMAIL = process.env.E2E_TEST_USER_EMAIL ?? '';
const PASSWORD = process.env.E2E_TEST_USER_PASSWORD ?? '';

test.describe('Phase 4 — intake voice↔text handoff + process-till-now', () => {
  test.skip(!EMAIL || !PASSWORD, 'E2E credentials not configured');

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('#login-email').fill(EMAIL);
    await page.locator('#login-password').fill(PASSWORD);
    await page.locator('#login-submit').click();
    await expect(page).toHaveURL(/\/(home|intake|roles)/, { timeout: 10_000 });
  });

  test('voice → text mid-conversation, history intact', async ({ page }) => {
    test.skip(true, 'pending staging-fixture seeding helpers');
    // Start in voice, wait for an agent turn, click "Switch to chat" pill,
    // assert text-active stage mounts, assert TextMessageList contains prior turns.
  });

  test('text → voice mid-conversation with continuation primer', async ({ page }) => {
    test.skip(true, 'pending staging-fixture seeding helpers');
    // Start in text, send a message, click "Switch to call" pill,
    // assert voice-active stage mounts, assert orb + status reach "Connecting/Live".
  });

  test('two-tab conflict — tab B gets 409 toast, reconciles via Realtime', async ({ browser }) => {
    test.skip(true, 'pending staging-fixture seeding helpers');
    // ctxA starts voice. ctxB tries "Start with voice" → expects
    // #v2-intake-modality-conflict-toast to appear within 2s.
  });

  test('process-till-now: accept one diff updates current_answers', async ({ page }) => {
    test.skip(true, 'pending staging-fixture seeding helpers');
    // Click #v2-intake-process-till-now-button mid-conversation, wait for
    // diff panel #v2-intake-prefill-diff-panel to open, click Accept on first row,
    // assert PATCH /answers was called and CoverageTable row shows edited pip.
  });

  test('process-till-now: dismiss never writes to current_answers (invariant)', async ({ page, request }) => {
    test.skip(true, 'pending staging-fixture seeding helpers');
    // Click process-till-now button, wait for diff panel, click Dismiss on
    // every row + Close panel. GET /sessions/{id} and verify current_answers
    // is unchanged from the snapshot taken before reprocess was triggered.
    // This is the agent spec §9 invariant.
  });

  test('concurrent reprocess attempts → second one 409 with already-running banner', async ({ page }) => {
    test.skip(true, 'pending staging-fixture seeding helpers');
    // Click process-till-now twice in quick succession; second click should
    // surface reprocessError.type='already_running' (banner via store).
  });
});
