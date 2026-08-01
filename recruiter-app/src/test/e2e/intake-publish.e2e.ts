import { expect, test } from '@playwright/test';

/**
 * Happy path: home intake intent → voice call → end call → constructing_plan
 * streams the plan into the artifact → publish → deep-link into Manage with
 * the requisition preselected.
 */

test.describe.skip('intake → requisition publish happy path — superseded by Phase 5 e2e', () => {
  test('home → voice intake → constructing → publish → manage with req selected', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.locator('#home-title')).toBeVisible();

    const composer = page.locator('#app-shell-shell-chat-composer-input');
    await composer.fill("let's start an intake");
    await page.locator('#app-shell-shell-chat-composer-send').click();

    const intakeChip = page.locator('button[id^="home-transcript"][id$="-chip-intake"]');
    await expect(intakeChip).toBeVisible({ timeout: 5_000 });
    await intakeChip.click();
    await expect(page).toHaveURL(/\/intake$/);

    await page.locator('#intake-canvas-stage-mode-choice-agent-chip-call').click();

    const endCall = page.locator('#intake-canvas-stage-intake-voice-overlay-end');
    await expect(endCall).toBeVisible({ timeout: 5_000 });
    await endCall.click();

    const checklist = page.locator('#intake-canvas-stage-constructing-plan-checklist');
    await expect(checklist).toBeVisible({ timeout: 5_000 });

    const artifactHead = page.locator('#app-shell-shell-artifact-head');
    await expect(artifactHead).toBeVisible({ timeout: 10_000 });

    const artifactBody = page.locator('#app-shell-shell-artifact-body');
    const publishBtn = artifactBody
      .locator('button#\\:r0\\:-publish, button[id$="-publish"]')
      .first();
    await expect(publishBtn).toBeVisible({ timeout: 30_000 });
    await expect(publishBtn).toBeEnabled({ timeout: 30_000 });
    await publishBtn.click();

    const openInManage = page.locator('#intake-canvas-stage-publish-action-open');
    await expect(openInManage).toBeVisible({ timeout: 5_000 });
    await openInManage.click();

    await expect(page).toHaveURL(/\/manage\?.*reqId=requisition-pm-sfo/);
  });
});
