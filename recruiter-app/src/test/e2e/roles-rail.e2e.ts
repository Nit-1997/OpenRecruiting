import { expect, test } from '@playwright/test';

test.describe('P2 roles rail view', () => {
  test('/view/roles renders title + 3 tabs + search + table', async ({ page }) => {
    await page.goto('/view/roles');

    await expect(page.locator('#roles-view')).toBeVisible();
    await expect(page.locator('#roles-view-title')).toContainText('Roles');
    await expect(page.locator('#roles-view-new-btn')).toBeVisible();

    for (const tab of ['open', 'pending', 'closed']) {
      await expect(page.locator(`#roles-view-tab-${tab}`)).toBeVisible();
    }

    await expect(page.locator('#roles-view-search-input')).toBeVisible();
    await expect(page.locator('#roles-view-table')).toBeVisible();
  });

  test('tab switch filters rows — Closed shows paused roles', async ({ page }) => {
    await page.goto('/view/roles');
    await page.locator('#roles-view-tab-closed').click();

    await expect(page.locator('#roles-view-row-ds-rem')).toBeVisible();
    await expect(page.locator('#roles-view-row-fin-rem')).toBeVisible();
    await expect(page.locator('#roles-view-row-pm-sfo')).toHaveCount(0);
  });

  test('row click navigates to detail view with breadcrumb', async ({ page }) => {
    await page.goto('/view/roles');
    await page.locator('#roles-view-row-pm-sfo-trigger').click();

    await expect(page).toHaveURL('/view/roles/pm-sfo');
    await expect(page.locator('#role-detail')).toBeVisible();
    await expect(page.locator('#role-detail-breadcrumb')).toBeVisible();
    await expect(page.locator('#role-detail-breadcrumb-roles')).toContainText('Roles');
    await expect(page.locator('#role-detail-breadcrumb-current')).toContainText('Staff PM');

    // Chat stays — roles rail chat visible.
    await expect(page.locator('#app-shell-qna-chat')).toBeVisible();
  });

  test('Q&A chat answers the "stalling" intent with Data Scientist', async ({ page }) => {
    await page.goto('/view/roles');
    const input = page.locator('#app-shell-qna-chat-composer-input');
    await input.fill('any roles stalling?');
    await page.locator('#app-shell-qna-chat-composer-send').click();

    await expect(page.locator('#app-shell-qna-chat-scroll')).toContainText('Data Scientist');
  });

  test('+ New role button opens the inline modal form', async ({ page }) => {
    await page.goto('/view/roles');
    await page.locator('#roles-view-new-btn').click();

    await expect(page.locator('#roles-view-new-form')).toBeVisible();
    await expect(page.locator('#roles-view-new-form-title')).toContainText('New role');
    await expect(page.locator('#roles-view-new-form-f-title-input')).toBeVisible();

    await page.locator('#roles-view-new-form-close').click();
    await expect(page.locator('#roles-view-new-form')).toHaveCount(0);
  });
});
