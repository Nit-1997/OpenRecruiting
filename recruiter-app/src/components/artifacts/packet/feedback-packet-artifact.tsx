'use client';

import {
  AlertTriangle,
  ArrowRight,
  Check,
  Download,
  Flag,
  MessageSquare,
  Quote,
  RefreshCw,
} from 'lucide-react';
import type { FC, ReactNode } from 'react';
import type {
  FeedbackPacket,
  PacketQuoteType,
  PacketRound,
  PacketVerdict,
} from '@/fixtures/feedback-packets';
import { cn, pickAvatarFg } from '@/lib/utils';
import { useTypedArtifact } from '../_shared/use-artifact-data';

interface FeedbackPacketArtifactProps {
  id: string;
  artifactId: string;
}

// The fully-patched data shape for the `packet` artifact. The mock-stream
// runner seeds `{}` and patches fields in incrementally, so it extends
// `Partial<FeedbackPacket>` and the component guards every field.
export interface FeedbackPacketArtifactData extends Partial<FeedbackPacket> {
  flagged?: boolean;
  flaggedRoundId?: string | null;
  recommendedAdditional?: {
    title: string;
    rationale: string;
  } | null;
  replyDraft?: {
    open: boolean;
    body: string;
  } | null;
}

type PacketData = FeedbackPacketArtifactData;

const VERDICT_STYLES: Record<
  PacketVerdict,
  { bg: string; text: string; border: string; label: string }
> = {
  strong: {
    bg: 'bg-[#ECFDF5]',
    text: 'text-[#047857]',
    border: 'border-[#A7F3D0]',
    label: 'Strong hire',
  },
  mixed: {
    bg: 'bg-[#FFFBEB]',
    text: 'text-[#B45309]',
    border: 'border-[#FDE68A]',
    label: 'Mixed signal',
  },
  pass: {
    bg: 'bg-[#FEF2F2]',
    text: 'text-[#DC2626]',
    border: 'border-[#FCA5A5]',
    label: 'Do not advance',
  },
};

const SCORE_BAR_FILLS: Record<1 | 2 | 3 | 4, string> = {
  1: 'bg-[#F2D9D0]',
  2: 'bg-[#EDE4D1]',
  3: 'bg-[#D5E9DA]',
  4: 'bg-[#B9E1C5]',
};

export const FeedbackPacketArtifact: FC<FeedbackPacketArtifactProps> = ({ id, artifactId }) => {
  const artifact = useTypedArtifact(artifactId, 'packet');
  const data: PacketData = artifact?.data ?? {};
  const isBuilding = artifact?.isBuilding ?? false;
  const rounds = data.rounds ?? [];
  const verdict: PacketVerdict = data.overall?.verdict ?? 'mixed';
  const verdictStyle = VERDICT_STYLES[verdict];

  if (!artifact) return null;

  return (
    <section
      id={id}
      aria-busy={isBuilding}
      aria-label="Feedback packet artifact"
      className="flex min-w-0 flex-col"
    >
      <Header id={id} data={data} verdictStyle={verdictStyle} />
      <Summary id={id} data={data} />
      <ThreeColumnDigest id={id} data={data} />
      <RoundsSection id={id} rounds={rounds} flaggedRoundId={data.flaggedRoundId} />
      {data.panelistsPanel && data.panelistsPanel.length > 0 && (
        <PanelistsStrip id={id} data={data} />
      )}
      {data.recommendedAdditional && <RecommendedAdditional id={id} data={data} />}
      {data.replyDraft?.open && <ReplyDraft id={id} body={data.replyDraft.body} />}
      <ActionsFooter id={id} data={data} />
      {isBuilding && (
        <div
          id={`${id}-building`}
          className="mt-4 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
        >
          Streaming rounds...
        </div>
      )}
    </section>
  );
};

function Header({
  id,
  data,
  verdictStyle,
}: {
  id: string;
  data: PacketData;
  verdictStyle: (typeof VERDICT_STYLES)[PacketVerdict];
}) {
  return (
    <header
      id={`${id}-head`}
      className="mb-5 flex items-start justify-between gap-4 border-border border-b pb-5"
    >
      <div id={`${id}-head-left`} className="flex min-w-0 flex-1 items-start gap-3">
        {data.candidateAvatar && (
          <span
            id={`${id}-avatar`}
            aria-hidden
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full font-medium font-mono text-[14px] text-text-primary"
            style={{
              background: data.candidateColor ?? '#EADFD4',
              color: pickAvatarFg(data.candidateColor ?? '#EADFD4'),
            }}
          >
            {data.candidateAvatar}
          </span>
        )}
        <div id={`${id}-head-text`} className="min-w-0 flex-1">
          <div
            id={`${id}-eyebrow`}
            className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
          >
            Feedback packet · {data.roleTitle ?? 'role'}
          </div>
          <h2
            id={`${id}-headline`}
            className="mt-1.5 font-display text-[28px] text-text-primary leading-tight tracking-[-0.01em]"
          >
            {data.candidateName ?? 'Candidate'}
          </h2>
          <div
            id={`${id}-subhead`}
            className="mt-1.5 text-[13px] text-text-secondary leading-[1.4]"
          >
            {data.candidateStage ?? '—'}
            {data.recommendation ? (
              <>
                {' '}
                <span className="text-text-faint">·</span> <em>{data.recommendation}</em>
              </>
            ) : null}
          </div>
        </div>
      </div>
      <div id={`${id}-head-right`} className="flex shrink-0 flex-col items-end gap-2">
        <div
          id={`${id}-verdict`}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-medium font-sans text-[12px]',
            verdictStyle.bg,
            verdictStyle.text,
            verdictStyle.border,
          )}
        >
          <span
            id={`${id}-verdict-dot`}
            aria-hidden
            className={cn('h-1.5 w-1.5 rounded-full', verdictStyle.text.replace('text-', 'bg-'))}
          />
          <span id={`${id}-verdict-label`}>{verdictStyle.label}</span>
        </div>
        {typeof data.aggregateScore === 'number' && (
          <div id={`${id}-score`} className="text-right">
            <div
              id={`${id}-score-big`}
              className="font-display text-[28px] text-text-primary leading-none tracking-[-0.01em]"
            >
              {data.aggregateScore.toFixed(1)}
              <span id={`${id}-score-scale`} className="ml-1 font-mono text-[12px] text-text-faint">
                / {data.scoreScale ?? 4}
              </span>
            </div>
            <div
              id={`${id}-score-label`}
              className="mt-1 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]"
            >
              Aggregate
            </div>
          </div>
        )}
        {data.read && (
          <span
            id={`${id}-read-badge`}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-0.5 font-mono text-[10px] text-text-muted uppercase tracking-[0.14em]"
          >
            <Check strokeWidth={1.75} className="h-3 w-3" aria-hidden /> Read
          </span>
        )}
        {data.flagged && (
          <span
            id={`${id}-flag-badge`}
            className="inline-flex items-center gap-1.5 rounded-full border border-[#FDE68A] bg-[#FFFBEB] px-2.5 py-0.5 font-mono text-[#B45309] text-[10px] uppercase tracking-[0.14em]"
          >
            <Flag strokeWidth={1.75} className="h-3 w-3" aria-hidden /> Flagged
            {data.flaggedRoundId ? ` · ${data.flaggedRoundId.toUpperCase()}` : ''}
          </span>
        )}
      </div>
    </header>
  );
}

function Summary({ id, data }: { id: string; data: PacketData }) {
  if (!data.overall?.summary) return null;
  return (
    <section
      id={`${id}-summary`}
      aria-label="Packet summary"
      className="mb-5 rounded-[14px] border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-4 py-3.5"
    >
      <div
        id={`${id}-summary-eyebrow`}
        className="mb-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
      >
        Summary
      </div>
      <p
        id={`${id}-summary-prose`}
        className="font-display text-[18px] text-text-primary leading-[1.4] tracking-[-0.005em]"
      >
        {data.overall.summary}
      </p>
    </section>
  );
}

function DigestColumn({
  id,
  title,
  items,
  icon,
  accent,
}: {
  id: string;
  title: string;
  items: string[] | undefined;
  icon: ReactNode;
  accent: 'pos' | 'neg' | 'neu';
}) {
  const accentClass =
    accent === 'pos'
      ? 'text-[#047857] bg-[#ECFDF5]'
      : accent === 'neg'
        ? 'text-[#B45309] bg-[#FFFBEB]'
        : 'text-[#1D4ED8] bg-[#EFF6FF]';
  return (
    <section
      id={id}
      className="flex min-w-0 flex-col rounded-[14px] border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-4 py-3.5"
    >
      <div id={`${id}-head`} className="mb-2 flex items-center gap-2">
        <span
          id={`${id}-ic`}
          aria-hidden
          className={cn('flex h-5 w-5 items-center justify-center rounded-full', accentClass)}
        >
          {icon}
        </span>
        <div
          id={`${id}-title`}
          className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
        >
          {title}
        </div>
      </div>
      {items && items.length > 0 ? (
        <ul id={`${id}-list`} className="flex flex-col gap-2">
          {items.map((item, i) => (
            <li
              // biome-ignore lint/suspicious/noArrayIndexKey: bullet content is static per render
              key={i}
              id={`${id}-item-${i}`}
              className="text-[13px] text-text-secondary leading-[1.5]"
            >
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <div id={`${id}-empty`} className="text-[12.5px] text-text-muted italic leading-[1.5]">
          Nothing flagged yet.
        </div>
      )}
    </section>
  );
}

function ThreeColumnDigest({ id, data }: { id: string; data: PacketData }) {
  return (
    <section
      id={`${id}-digest`}
      aria-label="Strengths, watch-outs, and next steps"
      className="mb-5 grid gap-3 md:grid-cols-3"
    >
      <DigestColumn
        id={`${id}-digest-strengths`}
        title="Strengths"
        items={data.overall?.strengths}
        accent="pos"
        icon={<Check strokeWidth={1.75} className="h-3 w-3" />}
      />
      <DigestColumn
        id={`${id}-digest-watchouts`}
        title="Watch-outs"
        items={data.overall?.watchouts}
        accent="neg"
        icon={<AlertTriangle strokeWidth={1.75} className="h-3 w-3" />}
      />
      <DigestColumn
        id={`${id}-digest-next`}
        title="Next steps"
        items={data.overall?.nextSteps}
        accent="neu"
        icon={<ArrowRight strokeWidth={1.75} className="h-3 w-3" />}
      />
    </section>
  );
}

function RoundCard({ id, round, flagged }: { id: string; round: PacketRound; flagged: boolean }) {
  const fill = SCORE_BAR_FILLS[round.score];
  const scorePct = Math.max(12, Math.min(100, (round.score / 4) * 100));
  return (
    <article
      id={id}
      aria-label={`${round.title} round by ${round.interviewer}`}
      className={cn(
        'rounded-[14px] border bg-white px-4 py-3.5 transition-colors',
        flagged ? 'border-[#FDE68A] bg-[#FFFBEB]' : 'border-border',
      )}
    >
      <header id={`${id}-head`} className="flex items-start justify-between gap-3">
        <div id={`${id}-head-text`} className="min-w-0 flex-1">
          <h3
            id={`${id}-title`}
            className="font-display font-normal text-[18px] text-text-primary leading-tight tracking-[-0.005em]"
          >
            {round.title}
          </h3>
          <div
            id={`${id}-meta`}
            className="mt-0.5 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]"
          >
            {round.interviewer} · {round.date}
            {flagged ? ' · flagged' : ''}
          </div>
        </div>
        <div id={`${id}-score-wrap`} className="flex shrink-0 items-center gap-2">
          <span id={`${id}-score`} className="font-medium font-mono text-[12px] text-text-primary">
            {round.score}/4
          </span>
          <div
            id={`${id}-score-track`}
            aria-hidden
            className="relative h-1.5 w-16 overflow-hidden rounded-full bg-surface"
          >
            <div
              id={`${id}-score-fill`}
              className={cn('absolute inset-y-0 left-0 rounded-full', fill)}
              style={{ width: `${scorePct}%` }}
            />
          </div>
        </div>
      </header>
      <p id={`${id}-notes`} className="mt-2.5 text-[13px] text-text-secondary leading-[1.5]">
        {round.notes}
      </p>
      {round.quotes && round.quotes.length > 0 && (
        <ul id={`${id}-quotes`} className="mt-3 flex flex-col gap-2">
          {round.quotes.map((quote, qi) => (
            <QuoteLine
              // biome-ignore lint/suspicious/noArrayIndexKey: quote list is append-only per round
              key={qi}
              id={`${id}-quote-${qi}`}
              text={quote.text}
              type={quote.type}
              attribution={quote.attribution}
            />
          ))}
        </ul>
      )}
    </article>
  );
}

function QuoteLine({
  id,
  text,
  type,
  attribution,
}: {
  id: string;
  text: string;
  type: PacketQuoteType;
  attribution?: string | undefined;
}) {
  const toneClass =
    type === 'strength'
      ? 'bg-[#ECFDF5] text-[#047857] border-[#A7F3D0]'
      : 'bg-[#FFFBEB] text-[#B45309] border-[#FDE68A]';
  return (
    <li id={id} className="flex items-start gap-2.5">
      <span
        id={`${id}-pill`}
        className={cn(
          'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em]',
          toneClass,
        )}
      >
        <Quote strokeWidth={1.75} className="h-2.5 w-2.5" aria-hidden />
        {type === 'strength' ? 'Strength' : 'Concern'}
      </span>
      <div id={`${id}-body`} className="min-w-0 flex-1">
        <p id={`${id}-text`} className="text-[12.5px] text-text-primary italic leading-[1.5]">
          {text}
        </p>
        {attribution && (
          <p
            id={`${id}-attr`}
            className="mt-0.5 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]"
          >
            — {attribution}
          </p>
        )}
      </div>
    </li>
  );
}

function RoundsSection({
  id,
  rounds,
  flaggedRoundId,
}: {
  id: string;
  rounds: PacketRound[];
  flaggedRoundId: string | null | undefined;
}) {
  return (
    <section id={`${id}-rounds`} aria-label="Round-by-round feedback" className="mb-5">
      <div id={`${id}-rounds-eyebrow`} className="mb-3 flex items-center justify-between">
        <span
          id={`${id}-rounds-title`}
          className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
        >
          Round-by-round
        </span>
        <span id={`${id}-rounds-count`} className="font-mono text-[11px] text-text-muted">
          {rounds.length} rounds
        </span>
      </div>
      {rounds.length === 0 ? (
        <div
          id={`${id}-rounds-empty`}
          className="rounded-[14px] border border-border border-dashed bg-white px-5 py-6 text-center text-[12.5px] text-text-muted"
        >
          Rounds are still compiling...
        </div>
      ) : (
        <div id={`${id}-rounds-list`} className="flex flex-col gap-3">
          {rounds.map((r) => (
            <RoundCard
              key={r.id}
              id={`${id}-round-${r.id}`}
              round={r}
              flagged={flaggedRoundId === r.id}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function PanelistsStrip({ id, data }: { id: string; data: PacketData }) {
  const panel = data.panelistsPanel ?? [];
  return (
    <section
      id={`${id}-panelists`}
      aria-label="Panelist quick-view"
      className="mb-5 rounded-[14px] border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-4 py-3.5"
    >
      <div
        id={`${id}-panelists-eyebrow`}
        className="mb-3 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
      >
        Panelist quick-view
      </div>
      <div id={`${id}-panelists-grid`} className="grid gap-2 sm:grid-cols-2 md:grid-cols-3">
        {panel.map((p, i) => (
          <div
            // biome-ignore lint/suspicious/noArrayIndexKey: panel is a fixed list rendered once per packet
            key={`${p.name}-${i}`}
            id={`${id}-panelist-${i}`}
            className="flex items-center justify-between gap-3 rounded-[10px] border border-border bg-surface px-3 py-2"
          >
            <div id={`${id}-panelist-${i}-body`} className="min-w-0 flex-1">
              <div
                id={`${id}-panelist-${i}-name`}
                className="truncate font-medium font-sans text-[12.5px] text-text-primary"
              >
                {p.name}
              </div>
              <div
                id={`${id}-panelist-${i}-role`}
                className="truncate font-mono text-[10px] text-text-muted uppercase tracking-[0.14em]"
              >
                {p.role}
              </div>
            </div>
            <span
              id={`${id}-panelist-${i}-score`}
              className="shrink-0 font-medium font-mono text-[12px] text-text-primary"
            >
              {p.score.toFixed(1)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function RecommendedAdditional({ id, data }: { id: string; data: PacketData }) {
  const block = data.recommendedAdditional;
  if (!block) return null;
  return (
    <section
      id={`${id}-recommended`}
      aria-label="Recommended additional round"
      className="mb-5 rounded-[14px] border border-cortex-100 bg-cortex-50 px-4 py-3.5"
    >
      <div id={`${id}-recommended-head`} className="mb-2 flex items-center gap-2">
        <RefreshCw strokeWidth={1.75} className="h-3.5 w-3.5 text-cortex-500" aria-hidden />
        <div
          id={`${id}-recommended-title`}
          className="font-mono text-[10.5px] text-cortex-600 uppercase tracking-[0.18em]"
        >
          {block.title}
        </div>
      </div>
      <p id={`${id}-recommended-body`} className="text-[13px] text-text-secondary leading-[1.5]">
        {block.rationale}
      </p>
    </section>
  );
}

function ReplyDraft({ id, body }: { id: string; body: string }) {
  return (
    <section
      id={`${id}-reply`}
      aria-label="Reply draft"
      className="mb-5 rounded-[14px] border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-4 py-3.5"
    >
      <div id={`${id}-reply-head`} className="mb-2 flex items-center gap-2">
        <MessageSquare strokeWidth={1.75} className="h-3.5 w-3.5 text-text-muted" aria-hidden />
        <div
          id={`${id}-reply-title`}
          className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
        >
          Draft reply to panel
        </div>
      </div>
      <textarea
        id={`${id}-reply-textarea`}
        aria-label="Reply draft body"
        defaultValue={body}
        readOnly
        className="w-full resize-none rounded-[10px] border border-border bg-surface px-3 py-2 text-[13px] text-text-primary focus:outline-none"
        rows={4}
      />
      <div id={`${id}-reply-hint`} className="mt-2 text-[11.5px] text-text-muted">
        This is a stubbed draft — send is not wired yet.
      </div>
    </section>
  );
}

function ActionsFooter({ id, data }: { id: string; data: PacketData }) {
  return (
    <footer
      id={`${id}-footer`}
      className="mt-2 flex flex-wrap items-center justify-between gap-3 border-border border-t pt-4"
    >
      <div id={`${id}-footer-meta`} className="text-[12px] text-text-muted leading-[1.4]">
        Packet drafted by OpenRecruiting · synthesized from {(data.rounds ?? []).length} rounds · editable
        before send.
      </div>
      <div id={`${id}-footer-actions`} className="flex items-center gap-2">
        <button
          id={`${id}-action-flag`}
          type="button"
          className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-3 py-1.5 font-medium font-sans text-[12.5px] text-text-primary transition-colors hover:border-text-primary"
          disabled
          title="Use the chips in the chat to flag for follow-up."
        >
          <Flag strokeWidth={1.75} className="h-3.5 w-3.5" /> Flag
        </button>
        <button
          id={`${id}-action-reply`}
          type="button"
          className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-3 py-1.5 font-medium font-sans text-[12.5px] text-text-primary transition-colors hover:border-text-primary"
          disabled
          title="Use the chips in the chat to draft a reply."
        >
          <MessageSquare strokeWidth={1.75} className="h-3.5 w-3.5" /> Reply
        </button>
        <button
          id={`${id}-action-request`}
          type="button"
          className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-3 py-1.5 font-medium font-sans text-[12.5px] text-text-primary transition-colors hover:border-text-primary"
          disabled
          title="Use the chips in the chat to request another round."
        >
          <RefreshCw strokeWidth={1.75} className="h-3.5 w-3.5" /> Request round
        </button>
        <button
          id={`${id}-action-export`}
          type="button"
          className="inline-flex items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-3 py-1.5 font-medium font-sans text-[12.5px] text-white transition-colors hover:bg-[#222]"
          title="Export is a stub in this demo."
        >
          <Download strokeWidth={1.75} className="h-3.5 w-3.5" /> Export PDF
        </button>
      </div>
    </footer>
  );
}
