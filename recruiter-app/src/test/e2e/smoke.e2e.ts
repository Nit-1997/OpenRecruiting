import { expect, test } from '@playwright/test';

test.describe('P0 shell smoke', () => {
  test('loads home with greeting + action cards', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#home-title')).toBeVisible();
    await expect(page.locator('#home-actions')).toBeVisible();
    await expect(page.locator('#home-action-intake')).toBeVisible();
  });

  test('top tabs navigate to sub-agent canvases', async ({ page }) => {
    await page.goto('/');
    for (const tab of ['intake', 'manage', 'debrief', 'packets', 'sourcing', 'brain']) {
      await page.locator(`#app-shell-topbar-tabs-tab-${tab}`).click();
      await expect(page).toHaveURL(new RegExp(`/${tab}$`));
      await expect(page.locator(`#${tab}-canvas`)).toBeVisible();
    }
  });

  test('right rail navigates to view routes', async ({ page }) => {
    await page.goto('/');
    for (const view of ['roles', 'integrations']) {
      await page.locator(`#app-shell-rail-${view}`).click();
      await expect(page).toHaveURL(new RegExp(`/view/${view}$`));
      await expect(page.locator(`#${view}-view`)).toBeVisible();
    }
  });

  test('brand click returns home from any surface', async ({ page }) => {
    await page.goto('/debrief');
    await expect(page.locator('#debrief-canvas')).toBeVisible();
    await page.locator('#app-shell-topbar-brand').click();
    await expect(page).toHaveURL('/');
    await expect(page.locator('#home-title')).toBeVisible();
  });

  test('profile popover opens from rail avatar', async ({ page }) => {
    await page.goto('/');
    await page.locator('#app-shell-rail-profile').click();
    await expect(page.locator('#app-shell-rail-profile-popover')).toBeVisible();
    await expect(page.locator('#app-shell-rail-profile-popover-billing')).toBeVisible();
  });
});
