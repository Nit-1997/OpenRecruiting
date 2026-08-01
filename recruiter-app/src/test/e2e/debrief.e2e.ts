import { expect, test } from '@playwright/test';

test.describe('P2 debrief sub-agent', () => {
  test('/debrief renders the role picker at stage role_pick', async ({ page }) => {
    await page.goto('/debrief');

    await expect(page.locator('#debrief-canvas')).toBeVisible();
    await expect(page.locator('#debrief-canvas-eyebrow')).toContainText('role pick');

    const agentMsg = page.locator('#debrief-canvas-stage-role-pick-agent-prose');
    await expect(agentMsg).toContainText(/Which role.*debrief/i);

    await expect(page.locator('#debrief-canvas-stage-role-pick-picker')).toBeVisible();
    await expect(page.locator('#debrief-canvas-stage-role-pick-picker-tab-all')).toBeVisible();
  });

  test('clicking a role advances to candidate_pick + shows candidate picker', async ({ page }) => {
    await page.goto('/debrief');
    await page.locator('#debrief-canvas-stage-role-pick-picker-card-pm-sfo').click();

    await expect(page.locator('#debrief-canvas-eyebrow')).toContainText('candidate pick');
    await expect(page.locator('#debrief-canvas-stage-candidate-pick-picker')).toBeVisible();
    // Role title shows up in picker header.
    await expect(page.locator('#debrief-canvas-stage-candidate-pick-picker-title')).toContainText(
      'Staff PM',
    );
  });

  test('selecting 2 candidates enables Compare CTA', async ({ page }) => {
    await page.goto('/debrief');
    await page.locator('#debrief-canvas-stage-role-pick-picker-card-pm-sfo').click();

    await expect(page.locator('#debrief-canvas-stage-candidate-pick-picker')).toBeVisible();

    const confirmBtn = page.locator('#debrief-canvas-stage-candidate-pick-picker-confirm');
    await expect(confirmBtn).toBeDisabled();

    await page.locator('#debrief-canvas-stage-candidate-pick-picker-card-c1').click();
    await page.locator('#debrief-canvas-stage-candidate-pick-picker-card-c2').click();

    await expect(confirmBtn).toBeEnabled();
    await expect(confirmBtn).toContainText(/2 candidates/);
  });
});
