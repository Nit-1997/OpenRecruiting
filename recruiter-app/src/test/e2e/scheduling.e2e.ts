/**
 * E2E coverage for the role-detail scheduling flow.
 *
 * Closes the exact gap that allowed the timezone bug to ship: there were
 * 36 backend tests for /schedule but zero browser-level tests for the
 * modal that drives them. The bugs (free-text tz, default-time snap,
 * mandatory-field labels, display in viewer tz) all lived in the UI and
 * the FE→BE contract — places only an E2E can catch.
 *
 * Backend is mocked via `page.route` because no v2 backend is running
 * in the playwright job. The mocks return realistic v2-shaped responses
 * so the FE can render, the modal can submit, and the pipeline can
 * refresh.
 */

import { expect, type Page, type Route, test } from '@playwright/test';

// IDs the v2 schemas use. Stable UUIDs so we can assert payloads.
const ROLE_ID = '99f0814b-06a2-4618-8d19-d6eeeb014ee6';
const CANDIDATE_ID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1';
const ROUND_ID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1';
const CR_ID = 'cccccccc-cccc-cccc-cccc-ccccccccccc1';

interface CapturedSchedule {
  scheduled_at: string;
  scheduling_timezone: string;
  meeting_url: string;
  interviewer_email?: string;
  interviewer_name?: string;
}

/**
 * Wire up v2 API mocks. Returns a capture object the test can inspect
 * after submission. Centralised so each test doesn't re-state the same
 * fixtures.
 */
async function mockV2Backend(page: Page): Promise<{ schedule: CapturedSchedule | null }> {
  const captured: { schedule: CapturedSchedule | null } = { schedule: null };

  const role = {
    id: ROLE_ID,
    title: 'Senior Backend Engineer',
    location: 'San Francisco',
    status: 'planned',
    department: 'Engineering',
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    created_by: 'user_1',
    created_by_name: 'Nitin',
    organization_id: 'org_1',
    rounds: [
      {
        id: ROUND_ID,
        round_number: 1,
        name: 'Recruiter Screen',
        category: 'screening',
        duration_minutes: 30,
        description: null,
        skills: [],
        feedback_questions: [],
      },
    ],
  };

  const buildCandidateRound = (overrides: Partial<Record<string, unknown>> = {}) => ({
    id: CR_ID,
    candidate_id: CANDIDATE_ID,
    round_id: ROUND_ID,
    status: 'pending',
    scheduled_at: null,
    scheduling_timezone: null,
    interviewer_email: null,
    interviewer_name: null,
    meeting_url: null,
    rating: null,
    summary: null,
    processing_status: 'none',
    scorecard_status: 'pending',
    feedback_approved_at: null,
    feedback_approved_by_email: null,
    question_summaries: {},
    started_at: null,
    completed_at: null,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    ...overrides,
  });

  // GET /api/v2/roles/{id}  — role header
  await page.route(`**/api/v2/roles/${ROLE_ID}`, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(role),
    });
  });

  // GET /api/v2/roles/{id}/plan  — rounds + questions
  await page.route(`**/api/v2/roles/${ROLE_ID}/plan`, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ rounds: role.rounds }),
    });
  });

  // GET /api/v2/roles/{id}/candidates  — pipeline cards
  await page.route(`**/api/v2/roles/${ROLE_ID}/candidates*`, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            id: CANDIDATE_ID,
            name: 'Ada Lovelace',
            email: 'ada@example.com',
            requisition_id: ROLE_ID,
            status: 'active',
            created_at: '2026-04-01T00:00:00Z',
            updated_at: '2026-04-01T00:00:00Z',
            candidate_rounds: [buildCandidateRound()],
          },
        ],
        page: 1,
        page_size: 25,
        total: 1,
      }),
    });
  });

  // GET packet — drives the drawer
  await page.route(
    `**/api/v2/roles/${ROLE_ID}/candidates/${CANDIDATE_ID}/packet`,
    async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          candidate: {
            id: CANDIDATE_ID,
            name: 'Ada Lovelace',
            email: 'ada@example.com',
            requisition_id: ROLE_ID,
          },
          rounds: [
            {
              round: role.rounds[0],
              candidate_round: buildCandidateRound(),
              feedback_entries: [],
            },
          ],
        }),
      });
    },
  );

  // POST /api/v2/candidate-rounds/{cr_id}/schedule — what we're testing
  await page.route(`**/api/v2/candidate-rounds/${CR_ID}/schedule`, async (route: Route) => {
    if (route.request().method() !== 'POST') return route.continue();
    const body = JSON.parse(route.request().postData() || '{}') as CapturedSchedule;
    captured.schedule = body;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        candidate_round: buildCandidateRound({
          status: 'scheduled',
          scheduled_at: body.scheduled_at,
          scheduling_timezone: body.scheduling_timezone,
          meeting_url: body.meeting_url,
          interviewer_email: body.interviewer_email ?? null,
          interviewer_name: body.interviewer_name ?? null,
        }),
        assessment_instance: null,
        bot: {
          recall_bot_id: 'bot_test',
          status: 'created',
          meeting_url: body.meeting_url,
          scheduled_at: body.scheduled_at,
        },
      }),
    });
  });

  return captured;
}

async function openScheduleModal(page: Page) {
  await page.goto(`/view/roles/${ROLE_ID}`);

  // Pipeline tab is the default. Click the first round cell to open the
  // packet drawer. The cell is a `Schedule` link on a pending round.
  // Falls back to a clickable cell if the underline text changes.
  const scheduleCell = page.getByText('Schedule', { exact: true }).first();
  await expect(scheduleCell).toBeVisible({ timeout: 10_000 });
  await scheduleCell.click();

  // The packet drawer mounts. Inside it, the round pane has a
  // "Schedule" button — distinct from the cell. We disambiguate by role.
  const scheduleButton = page.getByRole('button', { name: /^Schedule$/ });
  await expect(scheduleButton).toBeVisible({ timeout: 10_000 });
  await scheduleButton.click();

  // Modal mounts.
  await expect(page.getByText('Schedule interview')).toBeVisible({ timeout: 5_000 });
}

test.describe('Scheduling flow', () => {
  test('modal opens with current wall-clock time pre-filled (not 30-min snap)', async ({
    page,
  }) => {
    await mockV2Backend(page);
    await openScheduleModal(page);

    const timeInput = page.locator('input[type="time"]').first();
    const filled = await timeInput.inputValue();
    expect(filled).toMatch(/^\d{2}:\d{2}$/);

    // The filled time must equal the current wall-clock (rounded to a
    // 1-minute window for clock skew between Date.now() at test start
    // and modal mount). The previous bug snapped to the NEXT 30-min
    // boundary, which we explicitly reject.
    const now = new Date();
    const expectedHour = now.getHours().toString().padStart(2, '0');
    const expectedMinute = now.getMinutes().toString().padStart(2, '0');
    const expectedTime = `${expectedHour}:${expectedMinute}`;
    // Allow ±1 minute for the read.
    const [filledHourStr, filledMinStr] = filled.split(':');
    const [expHourStr, expMinStr] = expectedTime.split(':');
    const filledMinutes = Number(filledHourStr) * 60 + Number(filledMinStr);
    const expMinutes = Number(expHourStr) * 60 + Number(expMinStr);
    expect(Math.abs(filledMinutes - expMinutes)).toBeLessThanOrEqual(1);
  });

  test('meeting URL is required — submit without it surfaces an inline error', async ({ page }) => {
    const captured = await mockV2Backend(page);
    await openScheduleModal(page);

    // Leave meeting URL blank, submit.
    const submit = page.getByRole('button', { name: /^Schedule$|^Saving…$/ }).last();
    await submit.click();

    await expect(page.getByText(/Meeting URL is required/i)).toBeVisible({ timeout: 3_000 });

    // The POST must not have fired.
    expect(captured.schedule).toBeNull();
  });

  test('interviewer email + name are optional — submit succeeds without them', async ({ page }) => {
    const captured = await mockV2Backend(page);
    await openScheduleModal(page);

    await page.locator('input[type="url"]').fill('https://zoom.us/j/12345');

    const submit = page.getByRole('button', { name: /^Schedule$|^Saving…$/ }).last();
    await submit.click();

    // Modal closes — assert by waiting for the heading to disappear.
    await expect(page.getByText('Schedule interview')).toBeHidden({ timeout: 5_000 });

    // The captured payload must include meeting_url but NOT
    // interviewer_email or interviewer_name (omitted, not empty string).
    expect(captured.schedule).not.toBeNull();
    expect(captured.schedule?.meeting_url).toBe('https://zoom.us/j/12345');
    expect(captured.schedule?.interviewer_email).toBeUndefined();
    expect(captured.schedule?.interviewer_name).toBeUndefined();
  });

  test('IANA tz select converts wall-clock → ISO-with-offset on submit', async ({ page }) => {
    const captured = await mockV2Backend(page);
    await openScheduleModal(page);

    // Set date one day in the future to dodge any past-time bumping.
    const tomorrow = new Date(Date.now() + 86_400_000);
    const isoDate = tomorrow.toISOString().slice(0, 10);
    await page.locator('input[type="date"]').fill(isoDate);
    await page.locator('input[type="time"]').fill('15:00');

    // Select America/New_York from the tz dropdown.
    const tzSelect = page.locator('select').first();
    await tzSelect.selectOption('America/New_York');

    await page.locator('input[type="url"]').fill('https://zoom.us/j/abc');

    const submit = page.getByRole('button', { name: /^Schedule$|^Saving…$/ }).last();
    await submit.click();

    await expect(page.getByText('Schedule interview')).toBeHidden({ timeout: 5_000 });

    expect(captured.schedule).not.toBeNull();
    expect(captured.schedule?.scheduling_timezone).toBe('America/New_York');
    // ISO with -04:00 (EDT, May 21 = DST) or -05:00 (EST, off-DST). Asserting
    // the offset shape — the FE must NOT send naive ISO without offset.
    expect(captured.schedule?.scheduled_at).toMatch(
      /^\d{4}-\d{2}-\d{2}T15:00:00(?:-0[45]:00|-0[45])$/,
    );
  });

  test('invalid email shows inline error, not a generic schedule failure', async ({ page }) => {
    const captured = await mockV2Backend(page);
    await openScheduleModal(page);

    await page.locator('input[type="url"]').fill('https://zoom.us/j/12345');
    await page.locator('input[type="email"]').fill('not-an-email');

    const submit = page.getByRole('button', { name: /^Schedule$|^Saving…$/ }).last();
    await submit.click();

    await expect(page.getByText(/interviewer email looks invalid/i)).toBeVisible({
      timeout: 3_000,
    });

    // Submit blocked locally — no POST.
    expect(captured.schedule).toBeNull();
  });
});
