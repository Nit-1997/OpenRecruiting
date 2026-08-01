'use client';

import { ChevronLeft, ChevronRight, Plus, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { ScreeningConfigPanel } from '@/components/screening/screening-config-panel';
import { useRequisitionStore } from '@/stores';
import type { RoundCategory } from '@/types';
import { FeedbackQuestionRow } from './feedback-question-row';
import { GuidelineRow } from './guideline-row';
import { RoundCategoryBadge } from './round-category-badge';

export interface RoundDetailViewProps {
  id: string;
  reqId: string;
  roundId: string;
  onBack: () => void;
  onNext: (nextRoundId: string) => void;
}

type Tab = 'details' | 'guidelines';

const CATEGORIES: RoundCategory[] = [
  'screening',
  'coding',
  'design',
  'behavioral',
  'domain',
  'culture',
  'panel',
  'assessment',
];

export function RoundDetailView({ id, reqId, roundId, onBack, onNext }: RoundDetailViewProps) {
  const req = useRequisitionStore((s) => s.requisitions[reqId]);
  const updateRound = useRequisitionStore((s) => s.updateRound);
  const addQuestion = useRequisitionStore((s) => s.addQuestion);
  const updateQuestion = useRequisitionStore((s) => s.updateQuestion);
  const deleteQuestion = useRequisitionStore((s) => s.deleteQuestion);
  const updateGuidelines = useRequisitionStore((s) => s.updateGuidelines);

  const [tab, setTab] = useState<Tab>('details');
  const [screeningOpen, setScreeningOpen] = useState(false);

  if (!req) return null;
  const round = req.rounds.find((r) => r.id === roundId);
  if (!round) return null;

  const screenable = round.aiScreenable === true || round.screeningAgentEnabled === true;

  const index = req.rounds.findIndex((r) => r.id === roundId);
  const isLast = index === req.rounds.length - 1;
  const next = isLast ? undefined : req.rounds[index + 1];

  const setGuideline = (i: number, patch: { title: string; description: string }) => {
    const next = round.guidelines.map((g, j) => (j === i ? patch : g));
    updateGuidelines(round.id, next);
  };

  const deleteGuideline = (i: number) => {
    updateGuidelines(
      round.id,
      round.guidelines.filter((_, j) => j !== i),
    );
  };

  const addGuideline = () => {
    updateGuidelines(round.id, [...round.guidelines, { title: 'New guideline', description: '' }]);
  };

  return (
    <section id={id} className="flex flex-col gap-5">
      <header className="flex items-center gap-3">
        <button
          id={`${id}-back`}
          type="button"
          onClick={onBack}
          aria-label="Back to rounds"
          className="flex h-8 w-8 items-center justify-center rounded-full border border-border bg-surface text-text-muted transition hover:text-text-primary"
        >
          <ChevronLeft strokeWidth={1.75} className="h-4 w-4" />
        </button>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
            Round {round.roundNumber}
          </span>
          <input
            id={`${id}-name`}
            type="text"
            value={round.name}
            onChange={(e) => updateRound(round.id, { name: e.target.value })}
            className="bg-transparent font-medium font-sans text-[18px] text-text-primary leading-tight tracking-[-0.005em] outline-none"
          />
        </div>
      </header>

      {screenable && (
        <div
          id={`${id}-ai-banner`}
          className="flex items-center gap-2.5 rounded-[12px] border border-cortex-500/30 bg-gradient-to-br from-cortex-500/[0.06] to-white px-3.5 py-2.5"
        >
          <span
            aria-hidden
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-cortex-500/10 text-cortex-500"
          >
            <BrandIcon className="h-3.5 w-3.5" />
          </span>
          <div className="flex flex-1 flex-col">
            <span className="font-medium font-mono text-[10.5px] text-cortex-500 uppercase tracking-[0.14em]">
              {round.screeningAgentEnabled ? 'OpenRecruiting hosts this round' : 'OpenRecruiting can host this round'}
            </span>
            <span className="text-[12px] text-text-muted">
              {round.screeningAgentEnabled
                ? 'Screening call, resume read, and recruiter screen all run on OpenRecruiting.'
                : 'Run this as a OpenRecruiting screening call — configure questions and invite candidates.'}
              {round.screeningAgentQuestions
                ? ` ${round.screeningAgentQuestions.length} question${round.screeningAgentQuestions.length === 1 ? '' : 's'} drafted.`
                : ''}
            </span>
          </div>
          <button
            id={`${id}-screening-config`}
            type="button"
            onClick={() => setScreeningOpen(true)}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-cortex-500 px-3 py-1.5 font-medium font-sans text-[12px] text-white transition hover:opacity-90"
          >
            <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5" />
            {round.screeningAgentEnabled ? 'Configure' : 'Set up'}
          </button>
        </div>
      )}

      {screeningOpen && (
        <ScreeningConfigPanel
          id={`${id}-screening-panel`}
          requisitionId={reqId}
          roundId={round.id}
          round={round}
          onClose={() => setScreeningOpen(false)}
        />
      )}

      <div className="flex items-center gap-3">
        <RoundCategoryBadge id={`${id}-category-badge`} category={round.category} />
        <select
          id={`${id}-category-select`}
          value={round.category}
          onChange={(e) => updateRound(round.id, { category: e.target.value as RoundCategory })}
          className="rounded-md border border-border bg-surface px-2 py-1 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em] outline-none focus:border-cortex-500"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <div
          id={`${id}-duration`}
          className="flex items-center gap-1.5 rounded-md border border-border bg-surface px-2 py-1"
        >
          <input
            id={`${id}-duration-input`}
            type="number"
            min={5}
            max={240}
            value={round.durationMinutes}
            onChange={(e) =>
              updateRound(round.id, { durationMinutes: Number(e.target.value) || 0 })
            }
            className="w-10 bg-transparent text-[12px] text-text-primary outline-none"
          />
          <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
            min
          </span>
        </div>
      </div>

      <div id={`${id}-tabs`} className="flex items-center gap-4 border-border border-b">
        <button
          id={`${id}-tab-details`}
          type="button"
          onClick={() => setTab('details')}
          className={`-mb-px border-b-2 px-0.5 py-2 font-mono text-[10.5px] uppercase tracking-[0.14em] transition ${
            tab === 'details'
              ? 'border-cortex-500 text-text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          Edit Details
        </button>
        <button
          id={`${id}-tab-guidelines`}
          type="button"
          onClick={() => setTab('guidelines')}
          className={`-mb-px border-b-2 px-0.5 py-2 font-mono text-[10.5px] uppercase tracking-[0.14em] transition ${
            tab === 'guidelines'
              ? 'border-cortex-500 text-text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          Guidelines ({round.guidelines.length})
        </button>
      </div>

      {tab === 'details' && (
        <div id={`${id}-tab-details-panel`} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
              Description
            </span>
            <textarea
              id={`${id}-description`}
              value={round.description}
              onChange={(e) => updateRound(round.id, { description: e.target.value })}
              rows={3}
              className="rounded-md border border-border bg-surface px-2.5 py-2 text-[13px] text-text-primary outline-none focus:border-cortex-500"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
              Skills (comma separated)
            </span>
            <input
              id={`${id}-skills`}
              type="text"
              value={round.skills.join(', ')}
              onChange={(e) =>
                updateRound(round.id, {
                  skills: e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
              className="rounded-md border border-border bg-surface px-2.5 py-2 text-[13px] text-text-primary outline-none focus:border-cortex-500"
            />
          </label>
        </div>
      )}

      {tab === 'guidelines' && (
        <div id={`${id}-tab-guidelines-panel`} className="flex flex-col gap-2">
          {round.guidelines.map((g, i) => (
            <GuidelineRow
              key={`${round.id}-g-${g.title}`}
              id={`${id}-g`}
              index={i}
              guideline={g}
              onSave={(p) => setGuideline(i, p)}
              onDelete={deleteGuideline}
            />
          ))}
          <button
            id={`${id}-guidelines-add`}
            type="button"
            onClick={addGuideline}
            className="flex items-center justify-center gap-1.5 rounded-[12px] border border-border border-dashed px-3 py-2 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em] transition hover:border-cortex-500/40 hover:text-text-primary"
          >
            <Plus strokeWidth={1.75} className="h-3.5 w-3.5" />
            Add guideline
          </button>
        </div>
      )}

      <section id={`${id}-questions`} className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
            Feedback Questions
          </span>
          <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
            {round.feedbackQuestions.length}{' '}
            {round.feedbackQuestions.length === 1 ? 'question' : 'questions'}
          </span>
        </div>
        <div className="flex flex-col gap-2">
          {round.feedbackQuestions.map((q) => (
            <FeedbackQuestionRow
              key={q.id}
              id={`${id}-q`}
              question={q}
              onSave={(patch) => updateQuestion(q.id, patch)}
              onDelete={deleteQuestion}
            />
          ))}
        </div>
        <button
          id={`${id}-questions-add`}
          type="button"
          onClick={() => addQuestion(round.id, { heading: 'New question', description: null })}
          className="flex items-center justify-center gap-1.5 rounded-[12px] border border-border border-dashed px-3 py-2 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em] transition hover:border-cortex-500/40 hover:text-text-primary"
        >
          <Plus strokeWidth={1.75} className="h-3.5 w-3.5" />
          Add question
        </button>
      </section>

      <footer className="mt-2 flex items-center justify-between border-border border-t pt-3">
        <button
          id={`${id}-footer-back`}
          type="button"
          onClick={onBack}
          className="flex items-center gap-1.5 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em] transition hover:text-text-primary"
        >
          <ChevronLeft strokeWidth={1.75} className="h-3.5 w-3.5" />
          Back
        </button>
        <button
          id={`${id}-next`}
          type="button"
          disabled={isLast}
          onClick={() => {
            if (next) onNext(next.id);
          }}
          className="flex items-center gap-1.5 rounded-full bg-text-primary px-3 py-1.5 font-mono text-[10.5px] text-bg uppercase tracking-[0.14em] transition hover:opacity-90 disabled:opacity-30"
        >
          Next Round
          <ChevronRight strokeWidth={1.75} className="h-3.5 w-3.5" />
        </button>
      </footer>
    </section>
  );
}
