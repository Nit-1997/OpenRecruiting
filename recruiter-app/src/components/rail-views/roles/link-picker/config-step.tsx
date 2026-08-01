'use client';

import { Search } from 'lucide-react';
import type { Candidate, Round, UntrackedInterview } from '@/domain';
import { cn } from '@/lib/utils';

/**
 * Step 2 of the Link-to-Existing picker: choose how to attach the interview
 * (new candidate vs merge into an existing one) and which round it was for.
 * Presentational only — all state is owned by the orchestrator.
 */
export function ConfigStep({
  id,
  untracked,
  rounds,
  candidates,
  emailMatchCandidate,
  mode,
  selectedCandidateId,
  selectedRoundId,
  candidateQuery,
  interviewerName,
  interviewerEmail,
  interviewDate,
  onModeChange,
  onCandidateChange,
  onRoundChange,
  onCandidateQuery,
  onInterviewerName,
  onInterviewerEmail,
  onInterviewDate,
}: {
  id: string;
  untracked: UntrackedInterview;
  rounds: Round[];
  candidates: Candidate[];
  emailMatchCandidate: Candidate | null;
  mode: 'new_candidate' | 'merge_existing';
  selectedCandidateId: string | null;
  selectedRoundId: string | null;
  candidateQuery: string;
  interviewerName: string;
  interviewerEmail: string;
  interviewDate: string;
  onModeChange: (m: 'new_candidate' | 'merge_existing') => void;
  onCandidateChange: (id: string) => void;
  onRoundChange: (id: string) => void;
  onCandidateQuery: (q: string) => void;
  onInterviewerName: (v: string) => void;
  onInterviewerEmail: (v: string) => void;
  onInterviewDate: (v: string) => void;
}) {
  // Warn only when merging into a candidate round that ALREADY has a completed
  // scorecard — processing/feedback would overwrite it (reversible via undo).
  const overridingScorecard =
    mode === 'merge_existing' &&
    !!selectedCandidateId &&
    !!selectedRoundId &&
    (candidates
      .find((c) => c.id === selectedCandidateId)
      ?.candidate_rounds?.some(
        (r) => r.round_id === selectedRoundId && r.scorecard_status === 'complete',
      ) ??
      false);

  return (
    <div id={id} className="flex flex-col gap-4">
      <fieldset id={`${id}-mode`} className="flex flex-col gap-2">
        <legend className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
          How to attach this interview
        </legend>
        <ModeOption
          id={`${id}-mode-new`}
          active={mode === 'new_candidate'}
          onClick={() => onModeChange('new_candidate')}
          title="Add as a new candidate"
          subtitle={`Create ${untracked.candidate_name} in this role's pipeline.`}
        />
        <ModeOption
          id={`${id}-mode-merge`}
          active={mode === 'merge_existing'}
          onClick={() => onModeChange('merge_existing')}
          title="Merge with an existing candidate"
          subtitle="Attach this interview as one of an existing candidate's rounds."
          hint={emailMatchCandidate ? `Email match in pipeline: ${emailMatchCandidate.name}` : null}
        />
      </fieldset>

      {overridingScorecard && (
        <p
          id={`${id}-override-warning`}
          className="rounded-[10px] border border-[#F5C97B] bg-[#FFF7E6] px-3 py-2 text-[12px] text-[#92510A]"
        >
          This candidate already has a completed scorecard for the selected round. Sending a
          feedback request or processing the transcript will overwrite it — you can undo this from
          the Untracked Interviews tab.
        </p>
      )}

      {mode === 'merge_existing' && (
        <div id={`${id}-cands`} className="flex flex-col gap-2">
          <label
            htmlFor={`${id}-cand-search`}
            className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]"
          >
            Candidate in this role
          </label>
          <div className="flex items-center rounded-[10px] border border-border bg-white px-3 py-2 focus-within:border-text-primary">
            <Search strokeWidth={1.75} className="mr-2 h-3.5 w-3.5 text-text-muted" />
            <input
              id={`${id}-cand-search`}
              type="text"
              value={candidateQuery}
              onChange={(e) => onCandidateQuery(e.target.value)}
              placeholder="Search candidates by name or email…"
              className="min-w-0 flex-1 border-0 bg-transparent text-[13px] text-text-primary placeholder:text-text-muted focus:outline-none"
            />
          </div>
          {candidates.length === 0 ? (
            <p
              id={`${id}-cands-empty`}
              className="rounded-[10px] border border-border border-dashed bg-surface/40 px-3 py-4 text-center text-[12px] text-text-muted"
            >
              No candidates in this role yet. Use "Add as new candidate" instead.
            </p>
          ) : (
            <ul id={`${id}-cands-list`} className="flex max-h-44 flex-col gap-1 overflow-y-auto">
              {candidates.map((c) => (
                <li key={c.id}>
                  <button
                    id={`${id}-cand-${c.id}`}
                    type="button"
                    onClick={() => onCandidateChange(c.id)}
                    className={cn(
                      'flex w-full items-start justify-between gap-3 rounded-[10px] border px-3 py-2 text-left transition-colors',
                      selectedCandidateId === c.id
                        ? 'border-text-primary bg-surface/60'
                        : 'border-transparent hover:border-border hover:bg-surface/40',
                    )}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] text-text-primary">{c.name}</span>
                      <span className="mt-0.5 block truncate text-[11.5px] text-text-muted">
                        {c.email}
                      </span>
                    </span>
                    {emailMatchCandidate?.id === c.id && (
                      <span className="shrink-0 rounded-full border border-[#A7F3D0] bg-[#ECFDF5] px-2 py-0.5 font-mono text-[#047857] text-[9.5px] uppercase tracking-[0.14em]">
                        email match
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div id={`${id}-round`} className="flex flex-col gap-2">
        <label
          htmlFor={`${id}-round-select`}
          className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]"
        >
          Which round was this interview for?
        </label>
        {rounds.length === 0 ? (
          <p
            id={`${id}-round-empty`}
            className="rounded-[10px] border border-border border-dashed bg-surface/40 px-3 py-4 text-center text-[12px] text-text-muted"
          >
            This role has no active rounds yet.
          </p>
        ) : (
          <select
            id={`${id}-round-select`}
            value={selectedRoundId ?? ''}
            onChange={(e) => onRoundChange(e.target.value)}
            className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
          >
            {rounds.map((r) => (
              <option key={r.id} value={r.id}>
                R{r.round_number} · {r.name} ({r.duration_minutes} min)
              </option>
            ))}
          </select>
        )}
      </div>

      <div id={`${id}-interviewer`} className="flex flex-col gap-2">
        <label
          htmlFor={`${id}-interviewer-email`}
          className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]"
        >
          Interviewer (to request feedback)
        </label>
        <input
          id={`${id}-interviewer-name`}
          type="text"
          value={interviewerName}
          onChange={(e) => onInterviewerName(e.target.value)}
          placeholder="Interviewer name (optional)"
          className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
        />
        <input
          id={`${id}-interviewer-email`}
          type="email"
          value={interviewerEmail}
          onChange={(e) => onInterviewerEmail(e.target.value)}
          placeholder="interviewer@company.com"
          className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
        />
      </div>

      <div id={`${id}-date`} className="flex flex-col gap-2">
        <label
          htmlFor={`${id}-date-input`}
          className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]"
        >
          Interview date
        </label>
        <input
          id={`${id}-date-input`}
          type="date"
          value={interviewDate}
          onChange={(e) => onInterviewDate(e.target.value)}
          className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
        />
      </div>
    </div>
  );
}

function ModeOption({
  id,
  active,
  onClick,
  title,
  subtitle,
  hint,
}: {
  id: string;
  active: boolean;
  onClick: () => void;
  title: string;
  subtitle: string;
  hint?: string | null;
}) {
  return (
    <button
      id={id}
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'flex flex-col items-start gap-1 rounded-[10px] border px-3 py-2.5 text-left transition-colors',
        active
          ? 'border-text-primary bg-surface/60'
          : 'border-border bg-white hover:border-text-primary',
      )}
    >
      <span className="flex items-center gap-2 font-medium text-[13px] text-text-primary">
        <span
          aria-hidden
          className={cn(
            'flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
            active ? 'border-text-primary' : 'border-border',
          )}
        >
          {active && <span className="h-2 w-2 rounded-full bg-text-primary" />}
        </span>
        {title}
      </span>
      <span className="text-[12px] text-text-muted">{subtitle}</span>
      {hint && (
        <span className="font-mono text-[#047857] text-[10px] uppercase tracking-[0.14em]">
          {hint}
        </span>
      )}
    </button>
  );
}
