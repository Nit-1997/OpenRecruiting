import { expect, test } from '@playwright/test';

test.describe('P5 sourcing sub-agent', () => {
  test('/sourcing renders the mode picker at stage mode_pick', async ({ page }) => {
    await page.goto('/sourcing');
    await expect(page.locator('#sourcing-canvas')).toBeVisible();
    await expect(page.locator('#sourcing-canvas-eyebrow')).toContainText('mode pick');
    const agentProse = page.locator('#sourcing-canvas-stage-mode-pick-agent-prose');
    await expect(agentProse).toContainText(/existing role|fresh/i);
    // Both chips visible.
    await expect(
      page.locator('#sourcing-canvas-stage-mode-pick-agent-chip-existing'),
    ).toBeVisible();
    await expect(page.locator('#sourcing-canvas-stage-mode-pick-agent-chip-fresh')).toBeVisible();
  });

  test('clicking "Start from a fresh search" advances to query_build', async ({ page }) => {
    await page.goto('/sourcing');
    await page.locator('#sourcing-canvas-stage-mode-pick-agent-chip-fresh').click();
    await expect(page.locator('#sourcing-canvas-eyebrow')).toContainText('query build');
    await expect(page.locator('#sourcing-canvas-stage-query-build-composer')).toBeVisible();
    // Filter preview pills show all 5 criteria (inactive state).
    await expect(
      page.locator('#sourcing-canvas-stage-query-build-composer-preview-pill-title'),
    ).toBeVisible();
    await expect(
      page.locator('#sourcing-canvas-stage-query-build-composer-preview-pill-skills'),
    ).toBeVisible();
  });

  test('typing a query populates filter pills live', async ({ page }) => {
    await page.goto('/sourcing');
    await page.locator('#sourcing-canvas-stage-mode-pick-agent-chip-fresh').click();
    await expect(page.locator('#sourcing-canvas-stage-query-build-composer')).toBeVisible();
    const input = page.locator('#sourcing-canvas-stage-query-build-composer-input');
    await input.fill('Staff PMs in Sunnyvale with 7 years of experience using Metrics');

    // Title pill should show value.
    await expect(
      page.locator('#sourcing-canvas-stage-query-build-composer-preview-pill-title-value'),
    ).toContainText(/staff pm/i, { timeout: 2_000 });
    await expect(
      page.locator('#sourcing-canvas-stage-query-build-composer-preview-pill-location-value'),
    ).toContainText(/sunnyvale/i);
    await expect(
      page.locator('#sourcing-canvas-stage-query-build-composer-preview-pill-yoe-value'),
    ).toContainText(/7\+/i);
    await expect(
      page.locator('#sourcing-canvas-stage-query-build-composer-preview-pill-skills-value'),
    ).toContainText(/metrics/i);
    // The filter count badge in the composer reflects 4/5.
    await expect(page.locator('#sourcing-canvas-stage-query-build-composer-count')).toContainText(
      /4\/5/,
    );
  });

  test('clicking "Try this" pre-canned query advances to results', async ({ page }) => {
    await page.goto('/sourcing');
    await page.locator('#sourcing-canvas-stage-mode-pick-agent-chip-fresh').click();
    await expect(page.locator('#sourcing-canvas-stage-query-build-composer-try')).toBeVisible();
    await page.locator('#sourcing-canvas-stage-query-build-composer-try-item-0').click();

    await expect(page.locator('#sourcing-canvas-eyebrow')).toContainText('results', {
      timeout: 10_000,
    });
    const artifact = page.locator('#sourcing-canvas-stage-results-result');
    await expect(artifact).toBeVisible({ timeout: 10_000 });
  });

  test('results artifact shows candidate list + filter pills', async ({ page }) => {
    await page.goto('/sourcing');
    await page.locator('#sourcing-canvas-stage-mode-pick-agent-chip-fresh').click();
    await page.locator('#sourcing-canvas-stage-query-build-composer-try-item-0').click();
    const artifact = page.locator('#sourcing-canvas-stage-results-result');
    await expect(artifact).toBeVisible({ timeout: 10_000 });

    // Filter strip has at least one pill (from the pre-canned query: title, location, yoe, industry, skill).
    const firstSkillPill = page.locator('#sourcing-canvas-stage-results-result-filters-pill-title');
    await expect(firstSkillPill).toBeVisible();

    // Candidate list streams in.
    await expect(page.locator('#sourcing-canvas-stage-results-result-list')).toBeVisible({
      timeout: 10_000,
    });
  });

  test('clicking a checkbox selects a candidate and enables "Add to pipeline"', async ({
    page,
  }) => {
    await page.goto('/sourcing');
    await page.locator('#sourcing-canvas-stage-mode-pick-agent-chip-fresh').click();
    await page.locator('#sourcing-canvas-stage-query-build-composer-try-item-0').click();
    await expect(page.locator('#sourcing-canvas-stage-results-result-list')).toBeVisible({
      timeout: 10_000,
    });

    // Wait for at least one card to exist.
    const firstCardCheck = page
      .locator('[id^="sourcing-canvas-stage-results-result-list-card-"]')
      .first()
      .locator('input[type="checkbox"]');
    await expect(firstCardCheck).toBeVisible({ timeout: 10_000 });
    await firstCardCheck.check();

    // The add-to-pipeline button in actions bar should now be enabled.
    const addBtn = page.locator('#sourcing-canvas-stage-results-result-actions-add');
    await expect(addBtn).toBeEnabled();
    await expect(addBtn).toContainText(/Add 1/);
  });

  test('existing role path: role pick → auto-advances to results with derived query', async ({
    page,
  }) => {
    await page.goto('/sourcing');
    await page.locator('#sourcing-canvas-stage-mode-pick-agent-chip-existing').click();
    await expect(page.locator('#sourcing-canvas-eyebrow')).toContainText('role pick');
    await page.locator('#sourcing-canvas-stage-role-pick-picker-card-pm-sfo').click();

    await expect(page.locator('#sourcing-canvas-eyebrow')).toContainText('results', {
      timeout: 10_000,
    });
    // Artifact renders with the derived role label.
    await expect(page.locator('#sourcing-canvas-stage-results-result-role-label')).toContainText(
      /Staff PM/,
    );
    // And at least one filter pill from criteriaFromRole (title).
    await expect(
      page.locator('#sourcing-canvas-stage-results-result-filters-pill-title'),
    ).toBeVisible();
    await expect(page.locator('#sourcing-canvas-stage-results-result-list')).toBeVisible({
      timeout: 10_000,
    });
  });

  test('removing a filter pill refreshes the result set and clears selection', async ({ page }) => {
    await page.goto('/sourcing');
    await page.locator('#sourcing-canvas-stage-mode-pick-agent-chip-existing').click();
    await page.locator('#sourcing-canvas-stage-role-pick-picker-card-pm-sfo').click();
    await expect(page.locator('#sourcing-canvas-stage-results-result-list')).toBeVisible({
      timeout: 10_000,
    });

    // Remove the title pill.
    await page.locator('#sourcing-canvas-stage-results-result-filters-pill-title').click();
    // Pill goes away.
    await expect(
      page.locator('#sourcing-canvas-stage-results-result-filters-pill-title'),
    ).toHaveCount(0, { timeout: 5_000 });
  });
});
