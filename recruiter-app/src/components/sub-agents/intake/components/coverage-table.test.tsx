import { describe, expect, it } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import { CoverageTable } from '@/components/sub-agents/intake/components/coverage-table';
import type { IntakeSession } from '@/types/intake';

const baseSession = (current: Record<string, unknown> = {}): IntakeSession => ({
  id: 'sess-1',
  requisition_id: 'req-1',
  user_id: 'u-1',
  organization_id: 'o-1',
  status: 'active',
  active_modality: 'voice',
  entry_point: null,
  form_data: {
    role_name: 'x',
    experience_min: 1,
    experience_max: 2,
    location: 'NYC',
    jd_text: null,
  },
  questions_version: '1',
  questions_snapshot: [
    { id: 'q4_must_haves', order: 4, topic: 'Must-haves', default_text: '' },
  ] as IntakeSession['questions_snapshot'],
  prefilled_answers: null,
  current_answers: current as IntakeSession['current_answers'],
  turns: [],
  process_stages: [],
  process_status: 'idle',
  process_error: null,
  interview_plan: null,
  created_at: '',
  updated_at: '',
});

const multiSession = (current: Record<string, unknown> = {}): IntakeSession => ({
  id: 'sess-2',
  requisition_id: 'req-2',
  user_id: 'u-1',
  organization_id: 'o-1',
  status: 'active',
  active_modality: 'voice',
  entry_point: null,
  form_data: {
    role_name: 'Eng',
    experience_min: 3,
    experience_max: 5,
    location: 'SF',
    jd_text: null,
  },
  questions_version: '1',
  questions_snapshot: [
    { id: 'q1_role_overview', order: 1, topic: 'Role overview', default_text: 'Describe the role' },
    { id: 'q2_rounds', order: 2, topic: 'Interview rounds', default_text: 'How many rounds?' },
    { id: 'q3_focus_areas', order: 3, topic: 'Focus areas', default_text: 'Key topics' },
    { id: 'q4_must_haves', order: 4, topic: 'Must-haves', default_text: 'Required skills' },
    { id: 'q5_nice_to_haves', order: 5, topic: 'Nice-to-haves', default_text: 'Bonus skills' },
    { id: 'q6_cultural_fit', order: 6, topic: 'Cultural fit', default_text: 'Team culture' },
    {
      id: 'q7_team_structure',
      order: 7,
      topic: 'Team structure',
      default_text: 'Who they report to',
    },
    { id: 'q8_red_flags', order: 8, topic: 'Red flags', default_text: 'Dealbreakers' },
    { id: 'q9_anything_else', order: 9, topic: 'Anything else', default_text: 'Open notes' },
  ] as IntakeSession['questions_snapshot'],
  prefilled_answers: null,
  current_answers: current as IntakeSession['current_answers'],
  turns: [],
  process_stages: [],
  process_status: 'idle',
  process_error: null,
  interview_plan: null,
  created_at: '',
  updated_at: '',
});

describe('CoverageTable (Phase 2 — editable)', () => {
  it('renders a row per question', () => {
    render(
      <CoverageTable
        session={baseSession({ q4_must_haves: { status: 'discussed', text: 'Python' } })}
      />,
    );
    expect(document.getElementById('v2-intake-coverage-row-q4_must_haves')).not.toBeNull();
  });

  it('renders the answer text', () => {
    const { container } = render(
      <CoverageTable
        session={baseSession({ q4_must_haves: { status: 'discussed', text: 'Python' } })}
      />,
    );
    expect(container.textContent).toContain('Python');
  });

  it('shows Edit button on every row', () => {
    render(
      <CoverageTable
        session={baseSession({ q4_must_haves: { status: 'discussed', text: 'Python' } })}
      />,
    );
    expect(document.getElementById('v2-intake-coverage-edit-btn-q4_must_haves')).not.toBeNull();
  });

  it('Edit click swaps row to editor', () => {
    render(
      <CoverageTable
        session={baseSession({ q4_must_haves: { status: 'discussed', text: 'Python' } })}
      />,
    );
    fireEvent.click(
      document.getElementById('v2-intake-coverage-edit-btn-q4_must_haves') as HTMLButtonElement,
    );
    expect(document.getElementById('v2-intake-editor-q4_must_haves')).not.toBeNull();
  });

  it('renders "edited" pip when manual_edit=true', () => {
    render(
      <CoverageTable
        session={baseSession({
          q4_must_haves: {
            status: 'discussed',
            text: 'Python',
            manual_edit: true,
            edited_at: '2026-05-28T10:00:00Z',
          },
        })}
      />,
    );
    expect(document.getElementById('v2-intake-coverage-pip-q4_must_haves')).not.toBeNull();
  });

  it('does NOT render pip when manual_edit is absent', () => {
    render(
      <CoverageTable
        session={baseSession({ q4_must_haves: { status: 'discussed', text: 'Python' } })}
      />,
    );
    expect(document.getElementById('v2-intake-coverage-pip-q4_must_haves')).toBeNull();
  });
});

describe('CoverageTable (hero checklist additions)', () => {
  it('header shows correct covered count out of total', () => {
    const session = multiSession({
      q1_role_overview: { status: 'validated', text: 'Frontend role' },
      q2_rounds: { status: 'discussed', text: '3 rounds' },
      q3_focus_areas: { status: 'needs_probe', text: null },
    });
    const { container } = render(<CoverageTable session={session} />);
    expect(container.textContent).toContain('2 of 9 goals covered');
  });

  it('header covered count reflects validated + discussed only', () => {
    const session = multiSession({
      q1_role_overview: { status: 'validated', text: 'Frontend role' },
      q2_rounds: { status: 'validated', text: '3 rounds' },
      q3_focus_areas: { status: 'discussed', text: 'System design' },
      q4_must_haves: { status: 'needs_probe', text: null },
      q5_nice_to_haves: { status: 'skipped', text: null },
    });
    const { container } = render(<CoverageTable session={session} />);
    expect(container.textContent).toContain('3 of 9 goals covered');
  });

  it('legend shows confirmed count (validated only)', () => {
    const session = multiSession({
      q1_role_overview: { status: 'validated', text: 'Frontend role' },
      q2_rounds: { status: 'validated', text: '3 rounds' },
      q3_focus_areas: { status: 'discussed', text: 'System design' },
    });
    const { container } = render(<CoverageTable session={session} />);
    expect(container.textContent).toContain('2 confirmed');
  });

  it('legend shows captured count (discussed but not validated)', () => {
    const session = multiSession({
      q1_role_overview: { status: 'validated', text: 'Frontend role' },
      q2_rounds: { status: 'discussed', text: '3 rounds' },
      q3_focus_areas: { status: 'discussed', text: 'System design' },
    });
    const { container } = render(<CoverageTable session={session} />);
    expect(container.textContent).toContain('2 captured');
  });

  it('legend shows to-go count (uncovered questions)', () => {
    const session = multiSession({
      q1_role_overview: { status: 'validated', text: 'Frontend role' },
      q2_rounds: { status: 'discussed', text: '3 rounds' },
    });
    const { container } = render(<CoverageTable session={session} />);
    expect(container.textContent).toContain('7 to go');
  });

  it('first needs_probe question shows "Now discussing" pill', () => {
    const session = multiSession({
      q1_role_overview: { status: 'validated', text: 'Frontend role' },
      q2_rounds: { status: 'needs_probe', text: null },
      q3_focus_areas: { status: 'needs_probe', text: null },
    });
    const { container } = render(<CoverageTable session={session} />);
    const pills = container.querySelectorAll('[id^="v2-intake-coverage-now-"]');
    expect(pills.length).toBe(1);
    expect(pills[0]?.textContent).toBe('Now discussing');
    expect(pills[0]?.id).toBe('v2-intake-coverage-now-q2_rounds');
  });

  it('only one "Now discussing" pill renders even with multiple needs_probe rows', () => {
    const session = multiSession({
      q1_role_overview: { status: 'needs_probe', text: null },
      q2_rounds: { status: 'needs_probe', text: null },
      q3_focus_areas: { status: 'needs_probe', text: null },
    });
    const { container } = render(<CoverageTable session={session} />);
    const pills = container.querySelectorAll('[id^="v2-intake-coverage-now-"]');
    expect(pills.length).toBe(1);
  });

  it('progress ring renders with covered value visible', () => {
    const session = multiSession({
      q1_role_overview: { status: 'validated', text: 'Frontend role' },
      q2_rounds: { status: 'discussed', text: '3 rounds' },
      q3_focus_areas: { status: 'discussed', text: 'System design' },
    });
    render(<CoverageTable session={session} />);
    const legend = document.getElementById('v2-intake-coverage-legend');
    expect(legend).not.toBeNull();
    expect(document.getElementById('v2-intake-coverage-progress')).not.toBeNull();
  });

  it('no "Now discussing" pill when no needs_probe question', () => {
    const session = multiSession({
      q1_role_overview: { status: 'validated', text: 'Frontend role' },
      q2_rounds: { status: 'discussed', text: '3 rounds' },
    });
    const { container } = render(<CoverageTable session={session} />);
    const pills = container.querySelectorAll('[id^="v2-intake-coverage-now-"]');
    expect(pills.length).toBe(0);
  });

  it('rows maintain questions_snapshot order', () => {
    const session = multiSession({});
    const { container } = render(<CoverageTable session={session} />);
    const rows = container.querySelectorAll('[id^="v2-intake-coverage-row-"]');
    expect(rows[0]?.id).toBe('v2-intake-coverage-row-q1_role_overview');
    expect(rows[8]?.id).toBe('v2-intake-coverage-row-q9_anything_else');
  });

  it('all 9 rows render for a 9-question session', () => {
    const { container } = render(<CoverageTable session={multiSession()} />);
    const rows = container.querySelectorAll('[id^="v2-intake-coverage-row-"]');
    expect(rows.length).toBe(9);
  });
});
