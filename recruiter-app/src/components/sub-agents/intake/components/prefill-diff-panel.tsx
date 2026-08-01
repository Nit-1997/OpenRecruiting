'use client';

import { useMemo, useState } from 'react';

import { useIntakeSession } from '@/hooks/intake/use-intake-session';
import { useManualAnswerEdit } from '@/hooks/intake/use-manual-answer-edit';
import { useProcessTillNow } from '@/hooks/intake/use-process-till-now';
import { useIntakeStore } from '@/stores/intake-store';
import type { CurrentAnswers, QuestionId } from '@/types/intake';

interface DiffRow {
  qid: QuestionId;
  oldText: string;
  newText: string;
}

function computeDiffs(
  prefilled: CurrentAnswers | null | undefined,
  base: CurrentAnswers | null | undefined,
): DiffRow[] {
  if (!prefilled || !base) return [];
  const out: DiffRow[] = [];
  for (const qid of Object.keys(prefilled) as QuestionId[]) {
    const newText = prefilled[qid]?.text ?? '';
    const oldText = base[qid]?.text ?? '';
    if (newText !== oldText) {
      out.push({ qid, oldText, newText });
    }
  }
  return out;
}

export function PrefillDiffPanel() {
  const open = useIntakeStore((s) => s.diffPanelOpen);
  const baseAnswers = useIntakeStore((s) => s.diffBaseAnswers);
  const sessionId = useIntakeStore((s) => s.sessionId);
  const { session } = useIntakeSession(sessionId);
  const { saveEdit } = useManualAnswerEdit(sessionId);
  const { dismissDiffPanel } = useProcessTillNow();
  const [dismissedQids, setDismissedQids] = useState<Set<QuestionId>>(new Set());

  const allDiffs = useMemo(
    () => computeDiffs(session?.prefilled_answers, baseAnswers),
    [session?.prefilled_answers, baseAnswers],
  );

  const visibleDiffs = useMemo(
    () => allDiffs.filter((d) => !dismissedQids.has(d.qid)),
    [allDiffs, dismissedQids],
  );

  if (!open) return null;

  async function handleAccept(d: DiffRow) {
    await saveEdit(d.qid, { text: d.newText });
    setDismissedQids((prev) => new Set(prev).add(d.qid));
  }

  function handleDismiss(d: DiffRow) {
    setDismissedQids((prev) => new Set(prev).add(d.qid));
  }

  async function handleAcceptAll() {
    for (const d of visibleDiffs) {
      await saveEdit(d.qid, { text: d.newText });
    }
    setDismissedQids(new Set(allDiffs.map((d) => d.qid)));
  }

  return (
    <div
      id="v2-intake-prefill-diff-panel"
      data-testid="v2-intake-prefill-diff-panel"
      role="dialog"
      aria-labelledby="v2-intake-prefill-diff-title"
      className="fixed inset-y-0 right-0 z-40 w-full max-w-xl overflow-y-auto shadow-2xl"
      style={{ background: 'var(--app-card)', borderLeft: '1px solid var(--app-border)' }}
    >
      <header
        className="sticky top-0 flex items-center justify-between border-b px-6 py-4"
        style={{ borderColor: 'var(--app-border)', background: 'var(--app-card)' }}
      >
        <div>
          <h2
            id="v2-intake-prefill-diff-title"
            className="text-sm font-medium uppercase tracking-wide"
            style={{ color: 'var(--cortex-500)' }}
          >
            New suggestions from the conversation
          </h2>
          <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
            Accept any that improve your current answers. Nothing changes unless you accept it.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {visibleDiffs.length > 0 && (
            <button
              id="v2-intake-prefill-diff-accept-all"
              data-testid="v2-intake-prefill-diff-accept-all"
              type="button"
              onClick={() => void handleAcceptAll()}
              className="rounded px-3 py-1 text-xs font-medium uppercase"
              style={{ border: '1px solid var(--cortex-500)', color: 'var(--cortex-500)' }}
            >
              Accept all
            </button>
          )}
          <button
            id="v2-intake-prefill-diff-close"
            data-testid="v2-intake-prefill-diff-close"
            type="button"
            onClick={dismissDiffPanel}
            aria-label="Close diff panel"
            style={{ color: 'var(--text-muted)' }}
          >
            x
          </button>
        </div>
      </header>

      <div className="space-y-4 px-6 py-6">
        {visibleDiffs.length === 0 && (
          <div
            id="v2-intake-prefill-diff-empty"
            data-testid="v2-intake-prefill-diff-empty"
            className="rounded px-4 py-6 text-sm"
            style={{
              background: 'var(--app-secondary)',
              border: '1px solid var(--app-border)',
              color: 'var(--text-muted)',
            }}
          >
            No new suggestions — your current answers already match the latest prefill.
          </div>
        )}

        {visibleDiffs.map((d) => (
          <article
            key={d.qid}
            id={`v2-intake-prefill-diff-row-${d.qid}`}
            data-testid={`v2-intake-prefill-diff-row-${d.qid}`}
            className="rounded p-4"
            style={{ background: 'var(--app-secondary)', border: '1px solid var(--app-border)' }}
          >
            <div
              className="text-xs font-medium uppercase tracking-wide"
              style={{ color: 'var(--text-muted)' }}
            >
              {d.qid}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
              <div>
                <div
                  className="mb-1 text-xs uppercase tracking-wide"
                  style={{ color: 'var(--text-muted)' }}
                >
                  Current
                </div>
                <div
                  className="whitespace-pre-wrap rounded p-3"
                  style={{ background: 'var(--app-card)', color: 'var(--text-primary)' }}
                >
                  {d.oldText || <em style={{ color: 'var(--text-muted)' }}>(empty)</em>}
                </div>
              </div>
              <div>
                <div
                  className="mb-1 text-xs uppercase tracking-wide"
                  style={{ color: 'var(--cortex-500)' }}
                >
                  Suggested
                </div>
                <div
                  className="whitespace-pre-wrap rounded p-3"
                  style={{
                    background: 'var(--app-card)',
                    border: '1px solid var(--cortex-500)',
                    color: 'var(--text-primary)',
                  }}
                >
                  {d.newText || <em style={{ color: 'var(--text-muted)' }}>(empty)</em>}
                </div>
              </div>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <button
                id={`v2-intake-prefill-diff-accept-${d.qid}`}
                data-testid={`v2-intake-prefill-diff-accept-${d.qid}`}
                type="button"
                onClick={() => void handleAccept(d)}
                className="rounded px-3 py-1 text-xs font-medium uppercase"
                style={{ background: 'var(--cortex-500)', color: 'white' }}
              >
                Accept
              </button>
              <button
                id={`v2-intake-prefill-diff-dismiss-${d.qid}`}
                data-testid={`v2-intake-prefill-diff-dismiss-${d.qid}`}
                type="button"
                onClick={() => handleDismiss(d)}
                className="rounded px-3 py-1 text-xs uppercase"
                style={{ border: '1px solid var(--app-border)', color: 'var(--text-secondary)' }}
              >
                Dismiss
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
