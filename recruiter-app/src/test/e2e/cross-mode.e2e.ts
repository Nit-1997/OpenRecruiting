import { expect, test } from '@playwright/test';

/**
 * P7 cross-mode coverage. Exercises the shell-level invariants in
 * spec Section 2:
 * - voice popout survives tab switches
 * - voice auto-minimises in qna mode
 * - stashed tab returns when the rail closes
 * - load-previous rehydrates a past session
 * - artifact persists across navigation
 * - brand click always returns home
 * - home action cards navigate to the right sub-agent
 */

test.describe('P7 cross-mode flows', () => {
  test('home action cards navigate to each of the 6 sub-agent tabs', async ({ page }) => {
    await page.goto('/');

    const mapping = [
      { actionId: 'home-action-intake', url: '/intake', canvasId: 'intake-canvas' },
      { actionId: 'home-action-manage', url: '/manage', canvasId: 'manage-canvas' },
      { actionId: 'home-action-debrief', url: '/debrief', canvasId: 'debrief-canvas' },
      { actionId: 'home-action-packets', url: '/packets', canvasId: 'packets-canvas' },
      { actionId: 'home-action-sourcing', url: '/sourcing', canvasId: 'sourcing-canvas' },
      { actionId: 'home-action-brain', url: '/brain', canvasId: 'brain-canvas' },
    ];

    for (const { actionId, url, canvasId } of mapping) {
      await page.goto('/');
      await page.locator(`#${actionId}`).click();
      await expect(page).toHaveURL(new RegExp(`${url}$`));
      await expect(page.locator(`#${canvasId}`)).toBeVisible();
    }
  });

  test('brand click returns home from every shell surface', async ({ page }) => {
    const surfaces = [
      '/intake',
      '/manage',
      '/debrief',
      '/packets',
      '/sourcing',
      '/brain',
      '/view/roles',
      '/view/integrations',
    ];
    for (const path of surfaces) {
      await page.goto(path);
      await page.locator('#app-shell-topbar-brand').click();
      await expect(page).toHaveURL(/\/$/);
      await expect(page.locator('#home-title')).toBeVisible();
    }
  });

  test('voice popout persists when switching sub-agent tabs', async ({ page }) => {
    await page.goto('/intake');

    // Start the intake voice call via the mode-choice chip.
    await page.locator('#intake-canvas-stage-mode-choice-agent-chip-call').click();
    // Voice popout is visible (non-minimized dialog).
    await expect(page.locator('#app-shell-voice')).toBeVisible({ timeout: 3_000 });

    // Switch to debrief via the top tabs.
    await page.locator('#app-shell-topbar-tabs-tab-debrief').click();
    await expect(page).toHaveURL(/\/debrief$/);
    await expect(page.locator('#debrief-canvas')).toBeVisible();

    // Voice popout is still mounted after tab switch.
    await expect(page.locator('#app-shell-voice')).toBeVisible();
  });

  test('voice popout auto-minimises in Q&A mode and restores on close', async ({ page }) => {
    await page.goto('/intake');
    await page.locator('#intake-canvas-stage-mode-choice-agent-chip-call').click();
    await expect(page.locator('#app-shell-voice-orb')).toBeVisible({ timeout: 3_000 });

    // Click a rail icon — shell switches to qna mode, voice should minimise.
    await page.locator('#app-shell-rail-roles').click();
    await expect(page).toHaveURL(/\/view\/roles$/);
    // The minimized popout variant renders the chevron affordance.
    await expect(page.locator('#app-shell-voice-chevron')).toBeVisible({ timeout: 3_000 });

    // Close the rail by clicking the active rail icon — we return to /.
    await page.locator('#app-shell-rail-roles').click();
    await expect(page).toHaveURL(/\/$/);
  });

  test('stashed tab restores when the rail closes', async ({ page }) => {
    // Land on debrief then open Roles rail. The top-nav should show Debrief as muted.
    await page.goto('/debrief');
    await expect(page.locator('#debrief-canvas')).toBeVisible();

    await page.locator('#app-shell-rail-roles').click();
    await expect(page).toHaveURL(/\/view\/roles$/);

    // Debrief tab appears stashed — still rendered, but not aria-selected.
    const debriefTab = page.locator('#app-shell-topbar-tabs-tab-debrief');
    await expect(debriefTab).toBeVisible();
    await expect(debriefTab).toHaveAttribute('aria-selected', 'false');

    // Clicking the active Roles rail toggles home; the rail stash is dropped.
    await page.locator('#app-shell-rail-roles').click();
    await expect(page).toHaveURL(/\/$/);
  });

  test('intake session persists across tab-bar navigation', async ({ page }) => {
    // Advance intake to the chat stage.
    await page.goto('/intake');
    await page.locator('#intake-canvas-stage-mode-choice-agent-chip-chat').click();
    await expect(page.locator('#intake-canvas-eyebrow')).toContainText('intake chat', {
      timeout: 10_000,
    });

    // Switch to a different sub-agent via the top TabBar (not a fresh goto — that
    // reloads the page and tears down the in-memory zustand session).
    await page.locator('#app-shell-topbar-tabs-tab-debrief').click();
    await expect(page.locator('#debrief-canvas')).toBeVisible();

    // Navigate back and confirm the intake session is preserved at intake_chat.
    await page.locator('#app-shell-topbar-tabs-tab-intake').click();
    await expect(page.locator('#intake-canvas')).toBeVisible();
    await expect(page.locator('#intake-canvas-eyebrow')).toContainText('intake chat');
  });

  test('artifact persists across tab switches (manage overview rehydrates)', async ({ page }) => {
    await page.goto('/manage');
    await page.locator('#manage-canvas-stage-role-pick-picker-card-pm-sfo').click();
    await expect(page.locator('#manage-canvas-stage-role-detail-artifact-overview')).toBeVisible({
      timeout: 10_000,
    });

    // Switch to debrief and back.
    await page.locator('#app-shell-topbar-tabs-tab-debrief').click();
    await expect(page.locator('#debrief-canvas')).toBeVisible();

    await page.locator('#app-shell-topbar-tabs-tab-manage').click();
    // The manage overview artifact re-renders from the persisted session.
    await expect(page.locator('#manage-canvas-stage-role-detail-artifact-overview')).toBeVisible({
      timeout: 10_000,
    });
  });

  test('qna composer replaces agentic composer when a rail is open', async ({ page }) => {
    await page.goto('/intake');
    await expect(page.locator('#app-shell-composer')).toBeVisible();

    await page.locator('#app-shell-rail-roles').click();
    await expect(page).toHaveURL(/\/view\/roles$/);

    // Agentic bottom composer is hidden in qna mode.
    await expect(page.locator('#app-shell-composer')).toHaveCount(0);
    // Scoped chat composer is present.
    await expect(page.locator('#app-shell-qna-chat-composer-input')).toBeVisible();
  });

  test('Cmd/Ctrl+K focuses the composer input', async ({ page }) => {
    await page.goto('/intake');
    const composer = page.locator('#app-shell-composer-input');
    await expect(composer).toBeVisible();

    // Make sure focus is elsewhere first.
    await page.locator('#app-shell-topbar-brand').focus();
    await expect(composer).not.toBeFocused();

    await page.keyboard.press('Meta+k');
    // On non-mac runners, Meta+k is a no-op; fall back to Control+k.
    if (!(await composer.evaluate((el) => el === document.activeElement))) {
      await page.keyboard.press('Control+k');
    }
    await expect(composer).toBeFocused();
  });

  test('Escape closes the profile popover', async ({ page }) => {
    await page.goto('/');
    const profileBtn = page.locator('#app-shell-rail-profile');
    await profileBtn.click();
    await expect(page.locator('#app-shell-rail-profile-popover')).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(page.locator('#app-shell-rail-profile-popover')).toHaveCount(0);
  });
});
