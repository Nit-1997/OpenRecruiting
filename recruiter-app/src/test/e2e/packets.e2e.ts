import { expect, test } from '@playwright/test';

test.describe('P4 packets sub-agent', () => {
  test('/packets renders the role picker at stage role_pick', async ({ page }) => {
    await page.goto('/packets');
    await expect(page.locator('#packets-canvas')).toBeVisible();
    await expect(page.locator('#packets-canvas-eyebrow')).toContainText('role pick');
    const agentProse = page.locator('#packets-canvas-stage-role-pick-agent-prose');
    await expect(agentProse).toContainText(/Which role.*packet/i);
    await expect(page.locator('#packets-canvas-stage-role-pick-picker')).toBeVisible();
  });

  test('clicking a role advances to candidate_pick with the feedback candidate picker', async ({
    page,
  }) => {
    await page.goto('/packets');
    await page.locator('#packets-canvas-stage-role-pick-picker-card-pm-sfo').click();

    await expect(page.locator('#packets-canvas-eyebrow')).toContainText('candidate pick');
    const picker = page.locator('#packets-canvas-stage-candidate-pick-picker');
    await expect(picker).toBeVisible();
    // Role title shows in picker header.
    await expect(page.locator('#packets-canvas-stage-candidate-pick-picker-title')).toContainText(
      'Staff PM',
    );
    // Filter tabs differ from Debrief: All / Ready / Awaiting / Early (no Selected tab).
    await expect(page.locator('#packets-canvas-stage-candidate-pick-picker-tab-all')).toBeVisible();
    await expect(
      page.locator('#packets-canvas-stage-candidate-pick-picker-tab-ready'),
    ).toBeVisible();
    await expect(
      page.locator('#packets-canvas-stage-candidate-pick-picker-tab-waiting'),
    ).toBeVisible();
    await expect(
      page.locator('#packets-canvas-stage-candidate-pick-picker-tab-early'),
    ).toBeVisible();
  });

  test('clicking a candidate opens packet_view with the packet artifact visible', async ({
    page,
  }) => {
    await page.goto('/packets');
    await page.locator('#packets-canvas-stage-role-pick-picker-card-pm-sfo').click();
    await expect(page.locator('#packets-canvas-stage-candidate-pick-picker')).toBeVisible();

    await page.locator('#packets-canvas-stage-candidate-pick-picker-card-c1').click();

    await expect(page.locator('#packets-canvas-eyebrow')).toContainText('packet view');
    const artifact = page.locator('#packets-canvas-stage-packet-view-packet');
    await expect(artifact).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('#packets-canvas-stage-packet-view-packet-headline')).toContainText(
      'Sloane',
    );
    // Rounds-list eventually renders — wait for the first round card.
    await expect(page.locator('#packets-canvas-stage-packet-view-packet-round-rs')).toBeVisible({
      timeout: 10_000,
    });
  });

  test('typing "flag for follow-up" flags the lowest round', async ({ page }) => {
    await page.goto('/packets');
    await page.locator('#packets-canvas-stage-role-pick-picker-card-pm-sfo').click();
    await page.locator('#packets-canvas-stage-candidate-pick-picker-card-c3').click();
    await expect(page.locator('#packets-canvas-stage-packet-view-packet-round-hm')).toBeVisible({
      timeout: 10_000,
    });

    const input = page.locator('#app-shell-composer-input');
    await input.fill('flag for follow-up');
    await page.locator('#app-shell-composer-send').click();

    // Flag badge renders in the header.
    await expect(page.locator('#packets-canvas-stage-packet-view-packet-flag-badge')).toBeVisible({
      timeout: 5_000,
    });
  });

  test('clicking the Mark packet read chip flips the packet read flag', async ({ page }) => {
    await page.goto('/packets');
    await page.locator('#packets-canvas-stage-role-pick-picker-card-pm-sfo').click();
    await page.locator('#packets-canvas-stage-candidate-pick-picker-card-c1').click();
    await expect(page.locator('#packets-canvas-stage-packet-view-packet-round-rs')).toBeVisible({
      timeout: 10_000,
    });

    await page.locator('#packets-canvas-stage-packet-view-chip-mark-read').click();
    await expect(page.locator('#packets-canvas-stage-packet-view-packet-read-badge')).toBeVisible({
      timeout: 5_000,
    });
  });
});
