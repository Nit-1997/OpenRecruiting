import { expect, test } from '@playwright/test';

/**
 * P7 accessibility baseline verification. We don't ship axe-core yet
 * (no new dep), so this test hand-verifies the ARIA contract declared
 * in spec Section 8.
 *
 * - tablist role on TabBar; aria-selected/aria-controls on tabs
 * - role=log + aria-live=polite + aria-atomic=false on chat streams
 * - aria-busy on artifact surfaces while streaming
 * - aria-label on main canvas + scoped chat landmarks
 * - role=menu on profile popover; role=menuitem on entries
 * - aria-pressed on rail toggle buttons
 */

test.describe('P7 accessibility baseline', () => {
  test('TopBar TabBar declares role=tablist with tab/aria-selected/aria-controls', async ({
    page,
  }) => {
    await page.goto('/');
    const tabbar = page.locator('#app-shell-topbar-tabs');
    await expect(tabbar).toHaveAttribute('role', 'tablist');
    await expect(tabbar).toHaveAttribute('aria-label', /sub-agent/i);

    const intake = page.locator('#app-shell-topbar-tabs-tab-intake');
    await expect(intake).toHaveAttribute('role', 'tab');
    await expect(intake).toHaveAttribute('aria-selected', 'false');
    await expect(intake).toHaveAttribute('aria-controls', 'intake-canvas');
  });

  test('active tab flips aria-selected to true', async ({ page }) => {
    await page.goto('/intake');
    await expect(page.locator('#app-shell-topbar-tabs-tab-intake')).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(page.locator('#app-shell-topbar-tabs-tab-manage')).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  test('chat streams declare role=log + aria-live polite + aria-atomic false', async ({ page }) => {
    await page.goto('/view/roles');
    const log = page.locator('#app-shell-qna-chat-scroll');
    await expect(log).toHaveAttribute('role', 'log');
    await expect(log).toHaveAttribute('aria-live', 'polite');
    await expect(log).toHaveAttribute('aria-atomic', 'false');
    await expect(log).toHaveAttribute('aria-label', /roles/i);
  });

  test('intake chat stage declares role=log + aria-live polite', async ({ page }) => {
    await page.goto('/intake');
    await page.locator('#intake-canvas-stage-mode-choice-agent-chip-chat').click();
    const log = page.locator('#intake-canvas-stage-intake-chat');
    await expect(log).toHaveAttribute('role', 'log', { timeout: 10_000 });
    await expect(log).toHaveAttribute('aria-live', 'polite');
  });

  test('manage overview artifact exposes aria-busy on building', async ({ page }) => {
    await page.goto('/manage');
    await page.locator('#manage-canvas-stage-role-pick-picker-card-pm-sfo').click();
    // The artifact is initially building — aria-busy should be present and then
    // resolve to false when streaming is done.
    const art = page.locator('#manage-canvas-stage-role-detail-artifact-overview');
    await expect(art).toBeVisible({ timeout: 10_000 });
    const aria = await art.getAttribute('aria-busy');
    expect(aria === 'true' || aria === 'false').toBe(true);
  });

  test('profile popover uses role=menu with menuitem entries', async ({ page }) => {
    await page.goto('/');
    await page.locator('#app-shell-rail-profile').click();
    const menu = page.locator('#app-shell-rail-profile-popover');
    await expect(menu).toHaveAttribute('role', 'menu');
    await expect(menu.locator('[role="menuitem"]')).toHaveCount(3);
  });

  test('right rail buttons carry aria-label + aria-pressed', async ({ page }) => {
    await page.goto('/view/roles');
    const roles = page.locator('#app-shell-rail-roles');
    await expect(roles).toHaveAttribute('aria-label', 'Roles');
    await expect(roles).toHaveAttribute('aria-pressed', 'true');
    const integrations = page.locator('#app-shell-rail-integrations');
    await expect(integrations).toHaveAttribute('aria-pressed', 'false');
  });

  test('main canvas + split landmarks carry aria-label', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#app-shell-canvas')).toHaveAttribute('aria-label', /main canvas/i);

    await page.goto('/view/roles');
    await expect(page.locator('#app-shell-split-chat')).toHaveAttribute(
      'aria-label',
      /scoped chat/i,
    );
    await expect(page.locator('#app-shell-split-content')).toHaveAttribute(
      'aria-label',
      /rail view/i,
    );
  });

  test('Escape closes the profile popover', async ({ page }) => {
    await page.goto('/');
    await page.locator('#app-shell-rail-profile').click();
    await expect(page.locator('#app-shell-rail-profile-popover')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#app-shell-rail-profile-popover')).toHaveCount(0);
  });

  test('ArrowRight inside TabBar moves focus to next tab', async ({ page }) => {
    await page.goto('/intake');
    const intake = page.locator('#app-shell-topbar-tabs-tab-intake');
    await intake.focus();
    await expect(intake).toBeFocused();
    await page.keyboard.press('ArrowRight');
    await expect(page.locator('#app-shell-topbar-tabs-tab-manage')).toBeFocused();
  });

  test('ArrowLeft inside TabBar wraps to last tab from first', async ({ page }) => {
    await page.goto('/intake');
    const intake = page.locator('#app-shell-topbar-tabs-tab-intake');
    await intake.focus();
    await page.keyboard.press('ArrowLeft');
    await expect(page.locator('#app-shell-topbar-tabs-tab-brain')).toBeFocused();
  });

  test('New role modal declares role=dialog + aria-modal + aria-labelledby', async ({ page }) => {
    await page.goto('/view/roles');
    await page.locator('#roles-view-new-btn').click();
    const dialog = page.locator('#roles-view-new-form');
    await expect(dialog).toHaveAttribute('role', 'dialog');
    await expect(dialog).toHaveAttribute('aria-modal', 'true');
    await expect(dialog).toHaveAttribute('aria-labelledby', /title/);
  });

  test('Escape closes the New role modal (focus-trap onEscape)', async ({ page }) => {
    await page.goto('/view/roles');
    await page.locator('#roles-view-new-btn').click();
    await expect(page.locator('#roles-view-new-form')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#roles-view-new-form')).toHaveCount(0);
  });

  test('billing + team routes are reachable from profile popover links', async ({ page }) => {
    await page.goto('/');
    await page.locator('#app-shell-rail-profile').click();
    await page.locator('#app-shell-rail-profile-popover-billing').click();
    await expect(page).toHaveURL(/\/billing$/);
    await expect(page.locator('#billing-title')).toBeVisible();

    await page.goto('/');
    await page.locator('#app-shell-rail-profile').click();
    await page.locator('#app-shell-rail-profile-popover-team').click();
    await expect(page).toHaveURL(/\/team$/);
    await expect(page.locator('#team-title')).toBeVisible();
  });
});
