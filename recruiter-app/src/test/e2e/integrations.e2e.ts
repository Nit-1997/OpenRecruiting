import { expect, test } from '@playwright/test';

test.describe('P6 integrations rail view', () => {
  test('/view/integrations renders title + integration cards + workspace prefs', async ({
    page,
  }) => {
    await page.goto('/view/integrations');
    await expect(page.locator('#integrations-view')).toBeVisible();
    await expect(page.locator('#integrations-view-title')).toContainText('Integrations');

    // Slack card.
    await expect(page.locator('#integrations-view-slack')).toBeVisible();
    await expect(page.locator('#integrations-view-slack-title')).toContainText('Slack');
    await expect(page.locator('#integrations-view-slack-badge')).toContainText(/connected/i);

    // Workspace prefs block.
    await expect(page.locator('#integrations-view-prefs')).toBeVisible();
    await expect(page.locator('#integrations-view-prefs-timezone')).toBeVisible();
    await expect(page.locator('#integrations-view-prefs-recording')).toBeVisible();
    await expect(page.locator('#integrations-view-prefs-notifications')).toBeVisible();
  });

  test('clicking Slack Settings opens the inline panel', async ({ page }) => {
    await page.goto('/view/integrations');
    // Panel hidden by default.
    await expect(page.locator('#integrations-view-slack-settings-panel')).toHaveCount(0);

    await page.locator('#integrations-view-slack-settings-toggle').click();

    await expect(page.locator('#integrations-view-slack-settings-panel')).toBeVisible();
    await expect(
      page.locator('#integrations-view-slack-settings-field-channel-select'),
    ).toBeVisible();
    await expect(page.locator('#integrations-view-slack-settings-disconnect')).toBeVisible();
  });


  test('Q&A "disconnect slack" points at the Settings chip', async ({ page }) => {
    await page.goto('/view/integrations');
    const input = page.locator('#app-shell-qna-chat-composer-input');
    await input.fill('how do I disconnect slack');
    await page.locator('#app-shell-qna-chat-composer-send').click();

    await expect(page.locator('#app-shell-qna-chat-scroll')).toContainText(/cannot disconnect/i);
    await expect(page.locator('#app-shell-qna-chat-scroll')).toContainText(/Settings/i);
  });

  test('+ Add integration panel shows supported Connect buttons', async ({ page }) => {
    await page.goto('/view/integrations');
    await expect(page.locator('#integrations-view-add-grid')).toBeVisible();
    for (const key of ['greenhouse', 'lever']) {
      await expect(page.locator(`#integrations-view-add-card-${key}-connect`)).toBeVisible();
    }
  });

  test('Timezone selector persists change (local state)', async ({ page }) => {
    await page.goto('/view/integrations');
    const select = page.locator('#integrations-view-prefs-timezone-select');
    await expect(select).toBeVisible();

    await select.selectOption('Europe/London');
    await expect(select).toHaveValue('Europe/London');
  });

  test('Auto-join toggle in workspace prefs flips on click', async ({ page }) => {
    await page.goto('/view/integrations');
    const toggle = page.locator('#integrations-view-prefs-recording-toggle');
    await expect(toggle).toBeVisible();

    const initial = await toggle.getAttribute('aria-checked');
    await toggle.click();
    const after = await toggle.getAttribute('aria-checked');
    expect(initial).not.toBe(after);
  });
});
