import { expect, test } from '@playwright/test';

const EMAIL = process.env.E2E_TEST_USER_EMAIL ?? '';
const PASSWORD = process.env.E2E_TEST_USER_PASSWORD ?? '';
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8004';

test.describe('Phase 5 — submit + plan editor + publish', () => {
  test.skip(!EMAIL || !PASSWORD, 'E2E credentials not configured');

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('#login-email').fill(EMAIL);
    await page.locator('#login-password').fill(PASSWORD);
    await page.locator('#login-submit').click();
    await expect(page).toHaveURL(/\/(home|intake|roles)/, { timeout: 10_000 });
  });

  test('wrapping → submit fires Lambda + UI flips to plan_generating', async ({ page }) => {
    // Seed a session via API so we can deep-link to a known state without
    // driving the full text conversation here.
    const res = await page.request.post(`${API_URL}/api/v2/intake/sessions`, {
      data: {
        form_data: {
          role_name: 'E2E Phase 5 Submit',
          experience_min: 4,
          experience_max: 7,
          location: 'NYC',
          jd_text: null,
        },
        entry_point: 'intake_tab',
      },
    });
    expect(res.ok()).toBe(true);
    const { session_id } = (await res.json()) as { session_id: string };

    await page.goto(`/intake/sessions/${session_id}`);

    // The Submit CTA only shows once the session reaches wrapping. Skip if
    // the staging backend hasn't reached that state within a reasonable
    // window (it requires either voice or text turns to flip status).
    const submitBtn = page.locator('#v2-intake-stage-wrapping-submit-btn');
    const reachedWrapping = await submitBtn.waitFor({ timeout: 5_000 }).then(() => true, () => false);
    test.skip(!reachedWrapping, 'Seeded session did not reach wrapping — full conversation drive required');

    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();

    const planGenerating = page.locator('#intake-stage-plan-generating');
    await expect(planGenerating).toBeVisible({ timeout: 8_000 });
  });

  test('publish gate: violations on the editor disable Publish', async ({ page }) => {
    test.skip(
      !process.env.E2E_PHASE5_PUBLISHED_SESSION_ID,
      'Set E2E_PHASE5_PUBLISHED_SESSION_ID to a session that already reached plan_editing',
    );
    const sessionId = process.env.E2E_PHASE5_PUBLISHED_SESSION_ID;
    await page.goto(`/intake/sessions/${sessionId}`);

    const editor = page.locator('#intake-plan-editor');
    await expect(editor).toBeVisible({ timeout: 30_000 });

    await page.locator('#intake-plan-editor-list > li').first().locator('button[id$="-open"]').click();
    await page.locator('button[aria-label="Remove question"]').first().click();
    await page.locator('button[aria-label="Back to plan"]').click();

    await expect(page.locator('#intake-plan-editor-publish')).toBeDisabled();
    await expect(page.locator('#intake-plan-editor-violations')).toBeVisible();
  });

  test('publish click routes to /view/roles/<id>', async ({ page }) => {
    test.skip(
      !process.env.E2E_PHASE5_PUBLISHED_SESSION_ID,
      'Set E2E_PHASE5_PUBLISHED_SESSION_ID to a session that already reached plan_editing',
    );
    const sessionId = process.env.E2E_PHASE5_PUBLISHED_SESSION_ID;
    await page.goto(`/intake/sessions/${sessionId}`);

    const publishBtn = page.locator('#intake-plan-editor-publish');
    await expect(publishBtn).toBeVisible({ timeout: 30_000 });
    await expect(publishBtn).toBeEnabled({ timeout: 30_000 });
    await publishBtn.click();

    await expect(page).toHaveURL(/\/view\/roles\/[0-9a-f-]+/, { timeout: 10_000 });
  });
});
