'use client';

import { X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import type { Candidate, Round, UntrackedInterview } from '@/domain';
import { useCandidatesForRequisition, useRequisition } from '@/hooks/use-services';
import { cn } from '@/lib/utils';
import { ConfigStep } from './config-step';
import { RolePickStep } from './role-pick-step';
import { useLinkableRoles } from './use-linkable-roles';

export interface LinkToExistingConfirm {
  reqId: string;
  mode: 'new_candidate' | 'merge_existing';
  targetCandidateId?: string;
  targetRoundId?: string;
  interviewerEmail?: string;
  interviewerName?: string;
  scheduledAt?: string;
  /** What to do after associating: email the interviewer, or score the transcript now. */
  action: 'request_feedback' | 'process_transcript';
}

/**
 * Two-step dialog to attach an untracked interview to an existing role:
 *   1. RolePickStep   — pick the target role (full linkable list, fuzzy-ranked)
 *   2. ConfigStep     — new-vs-merge candidate + which round
 *
 * This component owns the wizard state and the per-role data (rounds,
 * candidates); the two steps are presentational.
 */
export function LinkToExistingPicker({
  id,
  untracked,
  onClose,
  onConfirm,
}: {
  id: string;
  untracked: UntrackedInterview;
  onClose: () => void;
  onConfirm: (options: LinkToExistingConfirm) => void | Promise<void>;
}) {
  const [step, setStep] = useState<'role' | 'config'>('role');
  const [selectedReqId, setSelectedReqId] = useState<string | null>(null);
  const [roleQuery, setRoleQuery] = useState('');
  const [mode, setMode] = useState<'new_candidate' | 'merge_existing'>('new_candidate');
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [selectedRoundId, setSelectedRoundId] = useState<string | null>(null);
  const [candidateQuery, setCandidateQuery] = useState('');
  // Interviewer + date attached to the round. Pre-filled from the captured
  // interview (the calendar interviewer + event date), both editable.
  const [interviewerName, setInterviewerName] = useState('');
  const [interviewerEmail, setInterviewerEmail] = useState(untracked.interviewer_email ?? '');
  const [interviewDate, setInterviewDate] = useState(
    untracked.event_start ? untracked.event_start.slice(0, 10) : '',
  );

  const selectedReq = useRequisition(selectedReqId);
  const pipelineCands = useCandidatesForRequisition(selectedReqId);

  // Every linkable role, fetched once and ranked client-side: by fuzzy match
  // to the meeting title by default, by the search box when the user types.
  // No server `q` round-trip, so search is instant and never 500s.
  const { roles: linkableRoles, loading: rolesLoading } = useLinkableRoles(
    untracked.event_title,
    roleQuery,
  );

  const reqRounds = useMemo<Round[]>(
    () =>
      (selectedReq.data?.rounds ?? []).filter(
        (r) => !r.for_candidate_id && !r.removed_from_plan_at,
      ),
    [selectedReq.data],
  );

  // Default the round selector to the first active round once rounds load.
  useEffect(() => {
    if (!selectedRoundId && reqRounds.length > 0) {
      setSelectedRoundId(reqRounds[0]?.id ?? null);
    }
  }, [selectedRoundId, reqRounds]);

  const filteredCands = useMemo<Candidate[]>(() => {
    const list = pipelineCands.data ?? [];
    const needle = candidateQuery.trim().toLowerCase();
    if (!needle) return list;
    return list.filter(
      (c) => c.name.toLowerCase().includes(needle) || c.email.toLowerCase().includes(needle),
    );
  }, [candidateQuery, pipelineCands.data]);

  // Surface a pipeline candidate whose email matches the capture as the most
  // likely merge target.
  const emailMatchCandidate = useMemo<Candidate | null>(() => {
    const list = pipelineCands.data ?? [];
    return (
      list.find((c) => c.email.toLowerCase() === untracked.candidate_email.toLowerCase()) ?? null
    );
  }, [pipelineCands.data, untracked.candidate_email]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  function pickRole(reqId: string): void {
    setSelectedReqId(reqId);
    setSelectedRoundId(null);
    setSelectedCandidateId(null);
    setMode('new_candidate');
    setStep('config');
  }

  function backToRole(): void {
    setStep('role');
    setSelectedReqId(null);
  }

  const canConfirm =
    !!selectedReqId && !!selectedRoundId && (mode === 'new_candidate' || !!selectedCandidateId);
  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(interviewerEmail.trim());

  function submit(action: LinkToExistingConfirm['action']): void {
    if (!canConfirm || !selectedReqId || !selectedRoundId) return;
    if (mode === 'merge_existing' && !selectedCandidateId) return;
    const opts: LinkToExistingConfirm = {
      reqId: selectedReqId,
      mode,
      targetRoundId: selectedRoundId,
      action,
    };
    if (mode === 'merge_existing' && selectedCandidateId) {
      opts.targetCandidateId = selectedCandidateId;
    }
    if (interviewerEmail.trim()) opts.interviewerEmail = interviewerEmail.trim();
    if (interviewerName.trim()) opts.interviewerName = interviewerName.trim();
    if (interviewDate) opts.scheduledAt = new Date(interviewDate).toISOString();
    void onConfirm(opts);
  }

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: non-interactive container that only stops click propagation to the untracked card it renders inside — dismissal is via the explicit close button + Escape handler.
    <div
      id={id}
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-[55] flex items-start justify-center bg-black/40 p-4 sm:items-center"
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        aria-label="Close picker"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-transparent"
      />
      <div className="relative w-full max-w-lg rounded-[16px] border border-border bg-white p-5 shadow-[0_20px_60px_rgba(0,0,0,0.2)]">
        <div className="mb-3 flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Link to existing
            </p>
            <h3 className="mt-1 font-display text-[18px] text-text-primary leading-tight">
              {step === 'role'
                ? 'Pick a role to import this interview into'
                : `Import into ${selectedReq.data?.role_title ?? 'role'}`}
            </h3>
            <p className="mt-1 truncate text-[12px] text-text-muted">
              {untracked.candidate_name} · {untracked.event_title}
            </p>
          </div>
          <button
            id={`${id}-close`}
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-text-muted hover:text-text-primary"
          >
            <X strokeWidth={1.75} className="h-4 w-4" />
          </button>
        </div>

        {step === 'role' ? (
          <RolePickStep
            id={`${id}-role`}
            roles={linkableRoles}
            query={roleQuery}
            loading={rolesLoading}
            onQuery={setRoleQuery}
            onPick={pickRole}
          />
        ) : (
          <ConfigStep
            id={`${id}-config`}
            untracked={untracked}
            rounds={reqRounds}
            candidates={filteredCands}
            emailMatchCandidate={emailMatchCandidate}
            mode={mode}
            selectedCandidateId={selectedCandidateId}
            selectedRoundId={selectedRoundId}
            candidateQuery={candidateQuery}
            interviewerName={interviewerName}
            interviewerEmail={interviewerEmail}
            interviewDate={interviewDate}
            onModeChange={(next) => {
              setMode(next);
              if (next === 'new_candidate') setSelectedCandidateId(null);
            }}
            onCandidateChange={setSelectedCandidateId}
            onRoundChange={setSelectedRoundId}
            onCandidateQuery={setCandidateQuery}
            onInterviewerName={setInterviewerName}
            onInterviewerEmail={setInterviewerEmail}
            onInterviewDate={setInterviewDate}
          />
        )}

        <div className="mt-4 flex items-center justify-between gap-2">
          {step === 'config' ? (
            <button
              id={`${id}-back`}
              type="button"
              onClick={backToRole}
              className="rounded-full border border-border bg-white px-3 py-1.5 text-[12.5px] text-text-muted hover:border-text-primary hover:text-text-primary"
            >
              ← Pick a different role
            </button>
          ) : (
            <span />
          )}
          {step === 'config' && (
            <div className="flex items-center gap-2">
              <button
                id={`${id}-process-transcript`}
                type="button"
                disabled={!canConfirm}
                onClick={() => submit('process_transcript')}
                title="Score the interview transcript now (quick rating only)"
                className={cn(
                  'rounded-full border px-3 py-2 font-medium text-[12.5px] transition-colors',
                  canConfirm
                    ? 'border-border bg-white text-text-primary hover:border-text-primary'
                    : 'cursor-not-allowed border-border bg-surface text-text-faint',
                )}
              >
                Process transcript
              </button>
              <button
                id={`${id}-request-feedback`}
                type="button"
                disabled={!canConfirm || !emailValid}
                onClick={() => submit('request_feedback')}
                title={
                  emailValid
                    ? 'Email the interviewer to capture feedback'
                    : 'Enter the interviewer email first'
                }
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full px-4 py-2 font-medium text-[12.5px] transition-colors',
                  canConfirm && emailValid
                    ? 'border border-text-primary bg-text-primary text-white hover:bg-[#222]'
                    : 'cursor-not-allowed border border-border bg-surface text-text-faint',
                )}
              >
                Send feedback request
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
