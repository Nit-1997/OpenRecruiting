import { expect, test } from '@playwright/test';

const EMAIL = process.env.E2E_TEST_USER_EMAIL ?? '';
const PASSWORD = process.env.E2E_TEST_USER_PASSWORD ?? '';

test.describe('Phase 1 — intake foundation', () => {
  test.skip(!EMAIL || !PASSWORD, 'E2E credentials not configured');

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('#login-email').fill(EMAIL);
    await page.locator('#login-password').fill(PASSWORD);
    await page.locator('#login-submit').click();
    await expect(page).toHaveURL(/\/(home|intake|roles)/, { timeout: 10_000 });
  });

  test('history list → new intake → form → prefilling → ready', async ({ page }) => {
    await page.goto('/intake');

    const history = page.locator('#intake-page-history');
    await expect(history).toBeVisible({ timeout: 10_000 });

    await page.locator('#intake-page-history-new-intake').click();

    const form = page.locator('#intake-page-canvas-stage-intake-form');
    await expect(form).toBeVisible({ timeout: 5_000 });

    await page.locator('#intake-page-canvas-stage-intake-form-role-name').fill('E2E Phase 1 Role');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-min').fill('3');
    await page.locator('#intake-page-canvas-stage-intake-form-exp-max').fill('7');
    await page.locator('#intake-page-canvas-stage-intake-form-location').fill('San Francisco');

    await page.locator('#intake-page-canvas-stage-intake-form-submit').click();

    const prefilling = page.locator('#intake-session-page-canvas-stage-prefilling');
    await expect(prefilling).toBeVisible({ timeout: 10_000 });

    await expect(
      page.locator('#intake-session-page-canvas-stage-prefilling-progress-row-check_context'),
    ).toBeVisible();
    await expect(
      page.locator('#intake-session-page-canvas-stage-prefilling-progress-row-parse_jd'),
    ).toBeVisible();
    await expect(
      page.locator('#intake-session-page-canvas-stage-prefilling-progress-row-query_cortex'),
    ).toBeVisible();
    await expect(
      page.locator('#intake-session-page-canvas-stage-prefilling-progress-row-synthesize'),
    ).toBeVisible();

    const ready = page.locator('#intake-session-page-canvas-stage-ready');
    await expect(ready).toBeVisible({ timeout: 60_000 });

    for (const qid of [
      'q1_role_overview',
      'q2_rounds',
      'q3_focus_areas',
      'q4_must_haves',
      'q5_nice_to_haves',
      'q6_cultural_fit',
      'q7_team_structure',
      'q8_red_flags',
      'q9_anything_else',
    ]) {
      await expect(
        page.locator(`#intake-session-page-canvas-stage-ready-coverage-card-${qid}`),
      ).toBeVisible();
    }
  });

  test('reload on /intake/sessions/[id] restores correct stage from row', async ({ page }) => {
    const res = await page.request.post(
      `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8004'}/api/v2/intake/sessions`,
      {
        data: {
          form_data: {
            role_name: 'E2E Reload Restore',
            experience_min: 2,
            experience_max: 5,
            location: 'Remote',
            jd_text: null,
          },
          entry_point: 'intake_tab',
        },
      },
    );
    expect(res.ok()).toBe(true);
    const { session_id } = (await res.json()) as { session_id: string };

    await page.goto(`/intake/sessions/${session_id}`);
    await page.reload();
    const prefilling = page.locator('#intake-session-page-canvas-stage-prefilling');
    const ready = page.locator('#intake-session-page-canvas-stage-ready');
    await expect(prefilling.or(ready)).toBeVisible({ timeout: 10_000 });
  });

  test('feature flag off hides /intake entry', async ({ page }) => {
    test.skip(
      process.env.E2E_TEST_USER_FLAG_OFF !== 'true',
      'Requires a separate test account with INTAKE_V2_ENABLED=false',
    );
    await page.goto('/intake');
    await expect(page.locator('#intake-page-disabled')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('#intake-page-history')).toHaveCount(0);
  });
});
