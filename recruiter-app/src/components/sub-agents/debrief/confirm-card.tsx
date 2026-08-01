'use client';

import { Brain, Check, X } from 'lucide-react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { ConfirmStatus, ProposedAction } from '@/types/sub-agent';

interface ConfirmCardProps {
  id: string;
  action: ProposedAction;
  status: ConfirmStatus;
  onConfirm: () => void;
  onDismiss: () => void;
  time?: string;
}

const STATUS_NOTE: Partial<Record<ConfirmStatus, string>> = {
  done: 'Applied.',
  failed: 'Could not apply.',
  dismissed: 'Dismissed.',
};

/**
 * Inline confirm card for a debrief `ProposedAction` (spec §5/§7). Renders the
 * agent's one-liner (`input.summary`) as the title and `input.rationale` as the
 * body, with Confirm / Dismiss actions. Once a decision is made the buttons are
 * replaced by a terminal note (applied / dismissed / could-not-apply). Purely
 * presentational — the flow owns the execute call and patches `status`.
 */
export function ConfirmCard({ id, action, status, onConfirm, onDismiss, time }: ConfirmCardProps) {
  // `executing` keeps the action row visible (buttons disabled) so the user sees
  // the in-flight state on the same control; only terminal states swap to a note.
  const settled = status === 'done' || status === 'failed' || status === 'dismissed';
  const note = STATUS_NOTE[status];
  // `propose_log_insight` writes a brain signal to Cortex rather than mutating
  // the pipeline — surface that distinction with a small badge so the recruiter
  // understands what confirming will (and won't) change.
  const isInsight = action.kind === 'propose_log_insight';

  return (
    <div id={id} className="flex max-w-[760px] items-start gap-3.5 py-2">
      <div
        id={`${id}-avatar`}
        aria-hidden
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white"
      >
        <BrandIcon className="h-6 w-6 text-text-primary" />
      </div>
      <div id={`${id}-body`} className="min-w-0 flex-1">
        <div
          id={`${id}-meta`}
          className="mb-1.5 flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
        >
          <span className="text-text-muted">openrecruiting debrief · suggested action</span>
          {time && <span>{time}</span>}
        </div>

        <Card id={`${id}-card`} className="max-w-[560px]">
          {isInsight && (
            <div
              id={`${id}-kind`}
              className="mb-1.5 inline-flex items-center gap-1.5 rounded-full bg-text-primary/[0.06] px-2 py-0.5 font-mono text-[10px] text-text-muted uppercase tracking-[0.12em]"
            >
              <Brain strokeWidth={2} className="h-3 w-3" aria-hidden />
              Log to Cortex
            </div>
          )}
          <h4 id={`${id}-title`} className="font-medium text-[14px] text-charcoal leading-snug">
            {action.input.summary}
          </h4>
          {action.input.rationale && (
            <p
              id={`${id}-rationale`}
              className="mt-1.5 text-[13px] text-text-secondary leading-[1.5]"
            >
              {action.input.rationale}
            </p>
          )}

          {settled ? (
            <div
              id={`${id}-status`}
              className={cn(
                'mt-3 inline-flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.14em]',
                status === 'failed' ? 'text-red-600' : 'text-text-muted',
              )}
            >
              {status === 'done' && <Check strokeWidth={2} className="h-3 w-3 text-[#3F8F5B]" />}
              {note}
            </div>
          ) : (
            <div id={`${id}-actions`} className="mt-3 flex items-center gap-2">
              <Button
                id={`${id}-confirm`}
                variant="primary"
                size="sm"
                disabled={status === 'executing'}
                icon={<Check strokeWidth={2} className="h-3.5 w-3.5" />}
                onClick={onConfirm}
              >
                {status === 'executing' ? 'Applying…' : 'Confirm'}
              </Button>
              <Button
                id={`${id}-dismiss`}
                variant="ghost"
                size="sm"
                disabled={status === 'executing'}
                icon={<X strokeWidth={2} className="h-3.5 w-3.5" />}
                onClick={onDismiss}
              >
                Dismiss
              </Button>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
