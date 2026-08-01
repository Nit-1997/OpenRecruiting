'use client';

import { Pencil } from 'lucide-react';
import { useState } from 'react';
import { GOAL_STATUS, ProgressRing, StatusMark } from '@/components/sub-agents/intake/primitives';
import { useManualAnswerEdit } from '@/hooks/intake/use-manual-answer-edit';
import type { AnswerState, AnswerStatus, IntakeSession, QuestionId } from '@/types/intake';
import { AnswerCardEditor } from './answer-card-editor';

interface Props {
  session: IntakeSession;
}

export function CoverageTable({ session }: Props) {
  const [editingQid, setEditingQid] = useState<QuestionId | null>(null);
  const { savingQid, error, saveEdit, clearError } = useManualAnswerEdit(session.id);
  const current = session.current_answers ?? {};
  const questions = session.questions_snapshot ?? [];

  const covered = questions.filter((q) => {
    const s = (current[q.id as QuestionId]?.status ?? 'untouched') as AnswerStatus;
    return s === 'validated' || s === 'discussed';
  }).length;

  const confirmed = questions.filter((q) => {
    const s = (current[q.id as QuestionId]?.status ?? 'untouched') as AnswerStatus;
    return s === 'validated';
  }).length;

  const currentGoalId = questions.find((q) => {
    const s = (current[q.id as QuestionId]?.status ?? 'untouched') as AnswerStatus;
    return s === 'needs_probe';
  })?.id;

  const handleSave = async (qid: QuestionId, patch: { text?: string; status?: AnswerStatus }) => {
    const res = await saveEdit(qid, patch);
    if (res) {
      setEditingQid(null);
    }
  };

  return (
    <div
      id="v2-intake-coverage-table"
      data-testid="v2-intake-coverage-table"
      className="mz-checklist"
      data-hero="true"
    >
      <div id="v2-intake-coverage-head" className="mz-check-head">
        <div>
          <div id="v2-intake-coverage-eyebrow" className="mz-eyebrow">
            Intake checklist
          </div>
          <h3 id="v2-intake-coverage-table-title" className="mz-check-title">
            {covered} of {questions.length} goals covered
          </h3>
        </div>

        <div id="v2-intake-coverage-progress" className="mz-check-progress">
          <ProgressRing value={covered} total={questions.length} size={60} stroke={5} />
          <div id="v2-intake-coverage-legend" className="mz-check-legend">
            <span id="v2-intake-coverage-legend-confirmed">
              <i style={{ background: 'var(--success-fg)' }} />
              {confirmed} confirmed
            </span>
            <span id="v2-intake-coverage-legend-captured">
              <i style={{ background: 'var(--cortex-500)' }} />
              {covered - confirmed} captured
            </span>
            <span id="v2-intake-coverage-legend-togo">
              <i style={{ background: 'var(--text-faint)' }} />
              {questions.length - covered} to go
            </span>
          </div>
        </div>
      </div>

      <div id="v2-intake-coverage-list" className="mz-goal-list">
        {questions.map((q) => {
          const qid = q.id as QuestionId;
          const a: AnswerState | undefined = current[qid];
          const status: AnswerStatus = a?.status ?? 'untouched';
          const isCurrentGoal = qid === currentGoalId;
          const isEditing = editingQid === qid;
          const isSaving = savingQid === qid;
          const goalStatus = GOAL_STATUS[status] ?? GOAL_STATUS.untouched;

          return (
            <div
              id={`v2-intake-coverage-row-${qid}`}
              data-testid={`v2-intake-coverage-row-${qid}`}
              key={qid}
              className={isCurrentGoal ? 'mz-goal mz-goal-current' : 'mz-goal'}
            >
              <StatusMark status={status} size={20} />

              <div style={{ minWidth: 0, flex: 1 }}>
                <div className="mz-goal-top">
                  <span id={`v2-intake-coverage-topic-${qid}`} className="mz-goal-topic">
                    {q.topic}
                  </span>

                  {isCurrentGoal ? (
                    <span
                      id={`v2-intake-coverage-now-${qid}`}
                      data-testid={`v2-intake-coverage-now-${qid}`}
                      className="mz-goal-now"
                    >
                      Now discussing
                    </span>
                  ) : (
                    <span
                      id={`v2-intake-coverage-status-${qid}`}
                      className="mz-goal-status"
                      style={{ color: goalStatus.dot }}
                    >
                      {goalStatus.label}
                    </span>
                  )}

                  {a?.manual_edit && (
                    <span
                      id={`v2-intake-coverage-pip-${qid}`}
                      data-testid={`v2-intake-coverage-pip-${qid}`}
                      title={
                        a.edited_at ? `Edited ${new Date(a.edited_at).toLocaleString()}` : 'Edited'
                      }
                      className="mz-goal-now"
                    >
                      edited
                    </span>
                  )}
                </div>

                {!isEditing &&
                  (a?.text ? (
                    <p id={`v2-intake-coverage-text-${qid}`} className="mz-goal-text">
                      {a.text}
                    </p>
                  ) : (
                    <p id={`v2-intake-coverage-hint-${qid}`} className="mz-goal-hint">
                      {isCurrentGoal ? 'OpenRecruiting is gathering this now…' : q.default_text}
                    </p>
                  ))}

                {isEditing && (
                  <div style={{ marginTop: 8 }}>
                    <AnswerCardEditor
                      qid={qid}
                      topic={q.topic}
                      initialText={a?.text ?? ''}
                      initialStatus={status}
                      saving={isSaving}
                      errorMessage={isSaving ? null : error}
                      onSave={(patch) => handleSave(qid, patch)}
                      onCancel={() => {
                        clearError();
                        setEditingQid(null);
                      }}
                    />
                  </div>
                )}
              </div>

              {!isEditing && (
                <button
                  id={`v2-intake-coverage-edit-btn-${qid}`}
                  data-testid={`v2-intake-coverage-edit-btn-${qid}`}
                  type="button"
                  onClick={() => {
                    clearError();
                    setEditingQid(qid);
                  }}
                  aria-label={`Edit ${q.topic}`}
                  className="mz-goal-edit"
                >
                  <Pencil size={13} />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
