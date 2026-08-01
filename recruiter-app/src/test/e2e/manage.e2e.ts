import { expect, test } from '@playwright/test';

test.describe('P3 manage sub-agent', () => {
  test('/manage renders the role picker at stage role_pick', async ({ page }) => {
    await page.goto('/manage');
    await expect(page.locator('#manage-canvas')).toBeVisible();
    await expect(page.locator('#manage-canvas-eyebrow')).toContainText('role pick');
    const agentProse = page.locator('#manage-canvas-stage-role-pick-agent-prose');
    await expect(agentProse).toContainText(/Which role.*manage/i);
    await expect(page.locator('#manage-canvas-stage-role-pick-picker')).toBeVisible();
  });

  test('clicking a role advances to role_detail with RoleOverview artifact visible', async ({
    page,
  }) => {
    await page.goto('/manage');
    await page.locator('#manage-canvas-stage-role-pick-picker-card-pm-sfo').click();

    await expect(page.locator('#manage-canvas-eyebrow')).toContainText('role detail');
    const overview = page.locator('#manage-canvas-stage-role-detail-artifact-overview');
    await expect(overview).toBeVisible({ timeout: 10_000 });
    await expect(
      page.locator('#manage-canvas-stage-role-detail-artifact-overview-headline'),
    ).toContainText(/Staff PM/);

    // Pipeline stages render.
    await expect(
      page.locator('#manage-canvas-stage-role-detail-artifact-overview-pipeline-sourced'),
    ).toBeVisible();
    await expect(
      page.locator('#manage-canvas-stage-role-detail-artifact-overview-pipeline-offer'),
    ).toBeVisible();
  });

  test('"Open requisition" chip swaps artifact to RequisitionDetail', async ({ page }) => {
    await page.goto('/manage');
    await page.locator('#manage-canvas-stage-role-pick-picker-card-pm-sfo').click();

    const overview = page.locator('#manage-canvas-stage-role-detail-artifact-overview');
    await expect(overview).toBeVisible({ timeout: 10_000 });

    await page.locator('#manage-canvas-stage-role-detail-chip-open-requisition').click();
    await expect(
      page.locator('#manage-canvas-stage-role-detail-artifact-requisition'),
    ).toBeVisible();
    await expect(
      page.locator('#manage-canvas-stage-role-detail-artifact-requisition-rounds-table'),
    ).toBeVisible();

    // Breadcrumb shows Requisition.
    await expect(page.locator('#manage-canvas-stage-role-detail-breadcrumb')).toContainText(
      'Requisition',
    );
  });

  test('breadcrumb click returns to RoleOverview', async ({ page }) => {
    await page.goto('/manage');
    await page.locator('#manage-canvas-stage-role-pick-picker-card-pm-sfo').click();
    const overview = page.locator('#manage-canvas-stage-role-detail-artifact-overview');
    await expect(overview).toBeVisible({ timeout: 10_000 });

    await page.locator('#manage-canvas-stage-role-detail-chip-open-requisition').click();
    await expect(
      page.locator('#manage-canvas-stage-role-detail-artifact-requisition'),
    ).toBeVisible();

    await page.locator('#manage-canvas-stage-role-detail-breadcrumb-overview-btn').click();
    await expect(page.locator('#manage-canvas-stage-role-detail-artifact-overview')).toBeVisible();
    await expect(page.locator('#manage-canvas-stage-role-detail-artifact-requisition')).toHaveCount(
      0,
    );
  });

  test('typing "add a take-home round" patches the requisition artifact', async ({ page }) => {
    await page.goto('/manage');
    await page.locator('#manage-canvas-stage-role-pick-picker-card-pm-sfo').click();
    await expect(page.locator('#manage-canvas-stage-role-detail-artifact-overview')).toBeVisible({
      timeout: 10_000,
    });
    await page.locator('#manage-canvas-stage-role-detail-chip-open-requisition').click();
    await expect(
      page.locator('#manage-canvas-stage-role-detail-artifact-requisition-rounds-table'),
    ).toBeVisible();

    // Count rounds before.
    const roundsBefore = await page
      .locator(
        '#manage-canvas-stage-role-detail-artifact-requisition-rounds-table > [id^="manage-canvas-stage-role-detail-artifact-requisition-round-"]',
      )
      .count();

    const input = page.locator('#app-shell-composer-input');
    await input.fill('add a take-home round');
    await page.locator('#app-shell-composer-send').click();

    // Row count grows.
    await expect
      .poll(
        async () => {
          return page
            .locator(
              '#manage-canvas-stage-role-detail-artifact-requisition-rounds-table > [id^="manage-canvas-stage-role-detail-artifact-requisition-round-"]',
            )
            .count();
        },
        { timeout: 5_000 },
      )
      .toBe(roundsBefore + 1);

    await expect(
      page.locator('#manage-canvas-stage-role-detail-artifact-requisition-round-th'),
    ).toBeVisible();
  });
});
