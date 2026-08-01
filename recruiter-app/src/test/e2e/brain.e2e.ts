import { expect, test } from '@playwright/test';

test.describe('P6 brain sub-agent', () => {
  test('/brain renders split canvas with force graph + story cards', async ({ page }) => {
    await page.goto('/brain');
    await expect(page.locator('#brain-canvas')).toBeVisible();
    await expect(page.locator('#brain-canvas-eyebrow')).toContainText(/Brain/i);

    // Force-directed graph renders.
    const svg = page.locator('#brain-canvas-stage-brain-canvas-graph-svg');
    await expect(svg).toBeVisible({ timeout: 10_000 });
    await expect(
      page.locator('#brain-canvas-stage-brain-canvas-graph-svg-node-i-ben'),
    ).toBeVisible();

    // Story cards strip.
    const stories = page.locator('#brain-canvas-stage-brain-canvas-stories-list');
    await expect(stories).toBeVisible({ timeout: 10_000 });
    await expect(
      page.locator('#brain-canvas-stage-brain-canvas-story-story-scoring-drift'),
    ).toBeVisible();
    await expect(
      page.locator('#brain-canvas-stage-brain-canvas-story-story-pipeline-risk'),
    ).toBeVisible();
  });

  test('clicking the "Explain" chip on scoring drift opens the drill-down + appends agent msg', async ({
    page,
  }) => {
    await page.goto('/brain');
    await expect(
      page.locator('#brain-canvas-stage-brain-canvas-story-story-scoring-drift'),
    ).toBeVisible({ timeout: 10_000 });

    await page
      .locator('#brain-canvas-stage-brain-canvas-story-story-scoring-drift-explain')
      .click();

    // Drill-down panel appears.
    await expect(page.locator('#brain-canvas-stage-brain-canvas-drilldown-story')).toBeVisible({
      timeout: 5_000,
    });
    await expect(
      page.locator('#brain-canvas-stage-brain-canvas-drilldown-story-title'),
    ).toContainText(/scoring drift/i);
    // Agent message in chat column reflects explanation.
    await expect(page.locator('#brain-canvas-stage-brain-chat-body')).toContainText(
      /scoring drift/i,
    );
  });

  test('typing "explain scoring drift" in the composer elaborates the story', async ({ page }) => {
    await page.goto('/brain');
    await expect(
      page.locator('#brain-canvas-stage-brain-canvas-story-story-scoring-drift'),
    ).toBeVisible({ timeout: 10_000 });

    const input = page.locator('#app-shell-composer-input');
    await input.fill('explain scoring drift');
    await page.locator('#app-shell-composer-send').click();

    // Chat receives agent response referencing Ben + Product Sense.
    await expect(page.locator('#brain-canvas-stage-brain-chat-body')).toContainText(/Ben/i, {
      timeout: 5_000,
    });
    await expect(page.locator('#brain-canvas-stage-brain-chat-body')).toContainText(
      /Product Sense/i,
    );
    await expect(page.locator('#brain-canvas-stage-brain-canvas-drilldown-story')).toBeVisible();
  });

  test('typing "mute panel load" removes the panel overload story card', async ({ page }) => {
    await page.goto('/brain');
    await expect(
      page.locator('#brain-canvas-stage-brain-canvas-story-story-panel-overload'),
    ).toBeVisible({ timeout: 10_000 });

    const input = page.locator('#app-shell-composer-input');
    await input.fill('mute panel load');
    await page.locator('#app-shell-composer-send').click();

    await expect(
      page.locator('#brain-canvas-stage-brain-canvas-story-story-panel-overload'),
    ).toHaveCount(0, { timeout: 5_000 });
    // But other stories remain.
    await expect(
      page.locator('#brain-canvas-stage-brain-canvas-story-story-scoring-drift'),
    ).toBeVisible();
  });

  test('clicking a node in the graph focuses it and shows the node drill-down', async ({
    page,
  }) => {
    await page.goto('/brain');
    const benNode = page.locator('#brain-canvas-stage-brain-canvas-graph-svg-node-i-ben');
    await expect(benNode).toBeVisible({ timeout: 10_000 });
    await benNode.click();

    await expect(page.locator('#brain-canvas-stage-brain-canvas-drilldown-node')).toBeVisible({
      timeout: 5_000,
    });
    await expect(
      page.locator('#brain-canvas-stage-brain-canvas-drilldown-node-title'),
    ).toContainText(/Ben/);
    // Clear focus chip should appear.
    await expect(page.locator('#brain-canvas-stage-brain-canvas-clear-focus')).toBeVisible();
  });

  test('range chips highlight the active range', async ({ page }) => {
    await page.goto('/brain');
    await expect(page.locator('#brain-canvas-stage-brain-canvas-range-this-week')).toBeVisible({
      timeout: 10_000,
    });
    await page.locator('#brain-canvas-stage-brain-canvas-range-quarter').click();
    // The active chip gets a text-primary background — verify via class presence.
    await expect(page.locator('#brain-canvas-stage-brain-canvas-range-quarter')).toHaveClass(
      /bg-text-primary/,
    );
  });
});
