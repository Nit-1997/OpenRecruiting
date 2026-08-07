import { expect, test } from '@playwright/test';

test.describe('P6 integrations rail view', () => {
  test('/view/integrations renders title + the connected cards', async ({ page }) => {
    await page.goto('/view/integrations');
    await expect(page.locator('#integrations')).toBeVisible();
    await expect(page.locator('#integrations-title')).toContainText('Integrations');

    await expect(page.locator('#integrations-ats')).toBeVisible();
    await expect(page.locator('#integrations-claude')).toBeVisible();
    await expect(page.locator('#integrations-claude-title')).toContainText('Claude');
    await expect(page.locator('#integrations-claude-badge')).toContainText('MCP');
  });

  test('the Claude card exposes its MCP endpoint and a copy button', async ({ page }) => {
    await page.goto('/view/integrations');
    await expect(page.locator('#integrations-claude-endpoint')).toBeVisible();
    await expect(page.locator('#integrations-claude-copy')).toBeVisible();
  });
});
