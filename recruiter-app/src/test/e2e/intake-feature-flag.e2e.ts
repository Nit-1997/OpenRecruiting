import { expect, test } from '@playwright/test';

const EMAIL = process.env.E2E_TEST_USER_EMAIL ?? '';
const PASSWORD = process.env.E2E_TEST_USER_PASSWORD ?? '';

test.describe('Phase 5 — INTAKE_V2_ENABLED feature flag gating', () => {
  test.skip(!EMAIL || !PASSWORD, 'E2E credentials not configured');

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('#login-email').fill(EMAIL);
    await page.locator('#login-password').fill(PASSWORD);
    await page.locator('#login-submit').click();
    await expect(page).toHaveURL(/\/(home|intake|roles)/, { timeout: 10_000 });
  });

  test('flag off → /intake renders disabled state, no history list', async ({ page }) => {
    test.skip(
      process.env.E2E_TEST_USER_FLAG_OFF !== 'true',
      'Requires E2E_TEST_USER_FLAG_OFF=true and a test account with INTAKE_V2_ENABLED=false',
    );
    await page.goto('/intake');
    await expect(page.locator('#intake-page-disabled')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('#intake-page-history')).toHaveCount(0);
  });

  test('flag on → /intake renders history list', async ({ page }) => {
    test.skip(
      process.env.E2E_TEST_USER_FLAG_OFF === 'true',
      'This test requires a flag-enabled account; E2E_TEST_USER_FLAG_OFF is set',
    );
    await page.goto('/intake');
    await expect(page.locator('#intake-page-history')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('#intake-page-disabled')).toHaveCount(0);
  });
});
