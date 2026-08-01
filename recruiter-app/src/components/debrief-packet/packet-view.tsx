'use client';

import { AlertTriangle, ArrowRight, CheckCircle2, Download, Sparkles, Users } from 'lucide-react';
import type {
  DebriefCandidateSnapshot,
  DebriefDecisionRow,
  DebriefPacket,
  DebriefTheme,
  DebriefVerdict,
  DebriefVote,
} from '@/fixtures/debrief-packets';
import { relativeTimeFrom } from '@/lib/relative-time';
import { cn, pickAvatarFg } from '@/lib/utils';
export const VERDICT_STYLE: Record<
  DebriefVerdict,
  { border: string; bg: string; text: string; dot: string; label: string }
> = {
  strong_hire: {
    border: 'border-[#A7F3D0]',
    bg: 'bg-[#ECFDF5]',
    text: 'text-[#047857]',
    dot: 'bg-[#059669]',
    label: 'Strong hire',
  },
  hire: {
    border: 'border-[#BFDBFE]',
    bg: 'bg-[#EFF6FF]',
    text: 'text-[#1D4ED8]',
    dot: 'bg-[#2563EB]',
    label: 'Hire',
  },
  mixed: {
    border: 'border-[#FDE68A]',
    bg: 'bg-[#FFFBEB]',
    text: 'text-[#B45309]',
    dot: 'bg-[#F59E0B]',
    label: 'Mixed signal',
  },
  no_hire: {
    border: 'border-[#FECACA]',
    bg: 'bg-[#FEF2F2]',
    text: 'text-[#B91C1C]',
    dot: 'bg-[#DC2626]',
    label: 'Do not advance',
  },
};

export const VOTE_STYLE: Record<DebriefVote, { bg: string; text: string; label: string }> = {
  strong_yes: { bg: 'bg-[#D1FAE5]', text: 'text-[#065F46]', label: 'Strong yes' },
  yes: { bg: 'bg-[#DBEAFE]', text: 'text-[#1E40AF]', label: 'Yes' },
  maybe: { bg: 'bg-[#FEF3C7]', text: 'text-[#92400E]', label: 'Maybe' },
  no: { bg: 'bg-[#FFE4E6]', text: 'text-[#9F1239]', label: 'No' },
  strong_no: { bg: 'bg-[#FEE2E2]', text: 'text-[#991B1B]', label: 'Strong no' },
};

function toneFor(value: number): 'strong' | 'okay' | 'weak' {
  if (value >= 3.4) return 'strong';
  if (value >= 2.8) return 'okay';
  return 'weak';
}

const TONE_FILL: Record<'strong' | 'okay' | 'weak', string> = {
  strong: 'bg-[#D5E9DA]',
  okay: 'bg-[#EDE4D1]',
  weak: 'bg-[#F2D9D0]',
};

export interface DebriefPacketToolbarProps {
  id: string;
  packet: DebriefPacket;
  trailing?: React.ReactNode;
}

/**
 * Shared top strip with the packet identity + a single Download action that
 * prints the already-rendered packet in place (`window.print()` → browser print
 * dialog → Save as PDF). The packet body is mounted into a `.print-portal`
 * alongside this toolbar by each caller, so the print captures the live packet
 * directly — no separate print route. Used by the role-detail drawer and the
 * debrief-agent artifact so both surfaces ship with the same affordance.
 */
export function DebriefPacketToolbar({ id, packet, trailing }: DebriefPacketToolbarProps) {
  const verdictStyle = VERDICT_STYLE[packet.verdict];

  return (
    <div
      id={`${id}-toolbar`}
      className="flex flex-wrap items-center justify-between gap-3 border-border border-b bg-white px-4 py-3 sm:px-6"
    >
      <div id={`${id}-toolbar-identity`} className="flex items-center gap-3">
        <span
          aria-hidden
          className="flex h-8 w-8 items-center justify-center rounded-full bg-cortex-50 text-cortex-600"
        >
          <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5" />
        </span>
        <div className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]">
          {packet.role_title} · generated {relativeTimeFrom(packet.generated_at)}
        </div>
        <span
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-medium font-sans text-[11px]',
            verdictStyle.border,
            verdictStyle.bg,
            verdictStyle.text,
          )}
        >
          <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', verdictStyle.dot)} />
          {verdictStyle.label}
        </span>
        {packet.status === 'superseded' && (
          <span className="rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[9.5px] text-text-muted uppercase tracking-[0.14em]">
            Superseded
          </span>
        )}
      </div>
      <div id={`${id}-toolbar-actions`} className="flex items-center gap-2">
        <button
          id={`${id}-download`}
          type="button"
          onClick={() => {
            if (typeof window !== 'undefined') window.print();
          }}
          className="inline-flex items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-3 py-1.5 font-medium font-sans text-[12px] text-white hover:bg-[#222] print:hidden"
          title="Save this packet as a PDF (opens the browser print dialog)"
        >
          <Download strokeWidth={1.75} className="h-3.5 w-3.5" />
          Download
        </button>
        {trailing}
      </div>
    </div>
  );
}

export interface DebriefPacketBodyProps {
  id: string;
  packet: DebriefPacket;
}

/**
 * The full packet body, rendered without any modal or scroll shell. The
 * caller chooses whether to wrap it in a fixed-position drawer, a
 * right-column artifact, or an inline preview — the visuals are the same.
 */
export function DebriefPacketBody({ id, packet }: DebriefPacketBodyProps) {
  const verdictStyle = VERDICT_STYLE[packet.verdict];
  const winner = packet.candidates[0] ?? null;
  const axesCount = packet.decision_matrix.length;
  return (
    <div id={id} className="flex flex-col gap-6">
      <ArtifactHeader id={`${id}-head`} packet={packet} winner={winner} axesCount={axesCount} />
      <RubricGrid
        id={`${id}-rubric`}
        rows={packet.decision_matrix}
        candidates={packet.candidates}
      />
      <CandidatePanels id={`${id}-panels`} candidates={packet.candidates} />
      <HeroRecommendation id={`${id}-rec`} packet={packet} verdictStyle={verdictStyle} />
      <Themes id={`${id}-themes`} themes={packet.themes} />
      <PanelGrid id={`${id}-panel`} packet={packet} />
      <RiskList id={`${id}-risks`} risks={packet.risks} />
      <NextSteps id={`${id}-next`} steps={packet.next_steps} />
    </div>
  );
}

function ArtifactHeader({
  id,
  packet,
  winner,
  axesCount,
}: {
  id: string;
  packet: DebriefPacket;
  winner: DebriefCandidateSnapshot | null;
  axesCount: number;
}) {
  const firstName = winner?.name.split(' ')[0] ?? 'the top candidate';
  return (
    <header id={id} className="flex flex-col gap-3 pb-1">
      <div
        id={`${id}-eyebrow`}
        className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
      >
        OpenRecruiting&apos;s read · Comparative debrief
      </div>
      <h1
        id={`${id}-title`}
        className="font-display text-[32px] text-text-primary leading-[1.15] tracking-[-0.01em]"
      >
        Strongest fit is <em className="font-display italic">{firstName}</em>, based on{' '}
        {packet.candidates.length} candidate{packet.candidates.length === 1 ? '' : 's'} across{' '}
        {axesCount} rubric axes.
      </h1>
      <p className="max-w-[700px] text-[13.5px] text-text-secondary leading-[1.55]">
        Pulled from{' '}
        <b className="font-medium text-text-primary">{packet.source_stats.scorecards} scorecards</b>{' '}
        and{' '}
        <b className="font-medium text-text-primary">
          {packet.source_stats.transcripts} transcript
          {packet.source_stats.transcripts === 1 ? '' : 's'}
        </b>
        . Weighted by interviewer calibration and rubric depth.
      </p>
    </header>
  );
}

function RubricGrid({
  id,
  rows,
  candidates,
}: {
  id: string;
  rows: DebriefDecisionRow[];
  candidates: DebriefCandidateSnapshot[];
}) {
  if (rows.length === 0 || candidates.length === 0) return null;
  const col = `220px repeat(${candidates.length}, minmax(140px, 1fr))`;
  return (
    <section
      id={id}
      aria-label="Rubric axes by candidate"
      className="overflow-x-auto rounded-[16px] border border-border/70 bg-white/95 shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
    >
      <div
        id={`${id}-head`}
        className="grid items-end gap-3 border-border border-b bg-surface/60 px-4 py-3"
        style={{ gridTemplateColumns: col }}
      >
        <div className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
          Dimension
        </div>
        {candidates.map((c, idx) => {
          const pct = Math.max(
            0,
            Math.min(100, Math.round((c.aggregate_score / c.score_scale) * 100)),
          );
          return (
            <div key={c.candidate_id} className="flex min-w-0 items-start gap-2">
              <span
                aria-hidden
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-medium font-mono text-[11px] text-text-primary"
                style={{ background: c.color, color: pickAvatarFg(c.color) }}
              >
                {c.initials}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate font-medium font-sans text-[13px] text-text-primary">
                    {c.name.split(' ')[0]}
                  </span>
                  {idx === 0 && (
                    <span className="rounded-full bg-text-primary px-1.5 py-0.5 font-mono text-[9px] text-white uppercase tracking-[0.14em]">
                      Recommend
                    </span>
                  )}
                </div>
                {c.aggregate_insufficient ? (
                  <div className="mt-0.5 font-mono text-[10.5px] text-text-faint italic">
                    Insufficient signal
                  </div>
                ) : (
                  <div className="mt-0.5 flex items-baseline gap-1 font-mono text-[10.5px] text-text-muted">
                    <span>{c.aggregate_score.toFixed(1)}</span>
                    <span>/ {c.score_scale.toFixed(1)}</span>
                    <span className="ml-auto">{pct}%</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="divide-y divide-border">
        {rows.map((row) => (
          <RubricRow
            key={row.dimension}
            id={`${id}-row-${row.dimension}`}
            col={col}
            row={row}
            candidates={candidates}
          />
        ))}
      </div>
    </section>
  );
}

function RubricRow({
  id,
  col,
  row,
  candidates,
}: {
  id: string;
  col: string;
  row: DebriefDecisionRow;
  candidates: DebriefCandidateSnapshot[];
}) {
  return (
    <div id={id} className="grid items-center gap-3 px-4 py-3" style={{ gridTemplateColumns: col }}>
      <div className="min-w-0">
        <div className="font-medium font-sans text-[13px] text-text-primary">{row.dimension}</div>
        <div className="mt-0.5 line-clamp-2 text-[11.5px] text-text-muted leading-[1.45]">
          {row.note}
        </div>
      </div>
      {candidates.map((c) => {
        const raw = row.scores[c.candidate_id];
        if (typeof raw !== 'number') {
          return (
            <div
              key={c.candidate_id}
              className="flex h-[36px] items-center justify-center rounded-[8px] border border-border border-dashed bg-surface font-mono text-[11px] text-text-faint"
            >
              —
            </div>
          );
        }
        const value = Math.min(4, Math.max(1, raw));
        const tone = toneFor(value);
        const pct = Math.max(0, Math.min(1, value / 4)) * 100;
        const isWinner = row.winner_ids.includes(c.candidate_id);
        return (
          <div
            key={c.candidate_id}
            id={`${id}-score-${c.candidate_id}`}
            className="relative h-[36px] min-w-0 overflow-hidden rounded-[8px] border border-border bg-surface text-left"
          >
            <span
              aria-hidden
              className={cn('absolute inset-0 h-full rounded-[8px]', TONE_FILL[tone])}
              style={{ width: `${pct}%` }}
            />
            <span className="relative flex h-full items-center justify-between px-2.5 font-medium font-mono text-[11.5px] text-text-primary">
              <span>{value.toFixed(1)}/4</span>
              {isWinner && (
                <span
                  role="img"
                  aria-label="Winner"
                  className="flex h-4 w-4 items-center justify-center rounded-full bg-white text-emerald-600"
                >
                  <CheckCircle2 strokeWidth={2} className="h-3 w-3" />
                </span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function CandidatePanels({
  id,
  candidates,
}: {
  id: string;
  candidates: DebriefCandidateSnapshot[];
}) {
  if (candidates.length === 0) return null;
  return (
    <section
      id={id}
      aria-label="Per-candidate panels"
      className={cn(
        'grid gap-3',
        candidates.length === 1
          ? 'grid-cols-1'
          : candidates.length === 2
            ? 'grid-cols-1 md:grid-cols-2'
            : 'grid-cols-1 md:grid-cols-2',
      )}
    >
      {candidates.map((c) => (
        <CandidatePanel key={c.candidate_id} id={`${id}-${c.candidate_id}`} c={c} />
      ))}
    </section>
  );
}

function CandidatePanel({ id, c }: { id: string; c: DebriefCandidateSnapshot }) {
  const verdictStyle = VERDICT_STYLE[c.verdict];
  return (
    <article
      id={id}
      className="flex flex-col gap-3 rounded-[16px] border border-border/70 bg-white/95 p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
    >
      <header className="flex items-center gap-3">
        <div className="relative">
          <span
            aria-hidden
            className="flex h-10 w-10 items-center justify-center rounded-full font-medium font-mono text-[12.5px] text-text-primary"
            style={{ background: c.color, color: pickAvatarFg(c.color) }}
          >
            {c.initials}
          </span>
          <span
            aria-hidden
            className="-bottom-1 -right-1 absolute flex h-5 w-5 items-center justify-center rounded-full border border-white bg-text-primary font-medium font-mono text-[10px] text-white"
          >
            {c.rank}
          </span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium font-sans text-[14px] text-text-primary">
            {c.name}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 font-mono text-[10.5px] text-text-muted">
            <span className={c.aggregate_insufficient ? 'text-text-faint italic' : undefined}>
              {c.aggregate_insufficient
                ? 'Insufficient signal'
                : `Weighted ${c.aggregate_score.toFixed(1)} / ${c.score_scale.toFixed(1)}`}
            </span>
            <span aria-hidden>·</span>
            <span>
              {c.rounds_completed}/{c.rounds_total} rounds
            </span>
          </div>
        </div>
        <span
          className={cn(
            'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 font-medium font-sans text-[10.5px]',
            verdictStyle.border,
            verdictStyle.bg,
            verdictStyle.text,
          )}
        >
          <span aria-hidden className={cn('h-1 w-1 rounded-full', verdictStyle.dot)} />
          {verdictStyle.label}
        </span>
      </header>

      <p className="text-[13px] text-text-secondary leading-[1.55]">{c.headline}</p>

      {c.top_strengths.length > 0 && (
        <div>
          <div className="mb-1 font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
            Strengths
          </div>
          <ul className="list-disc space-y-0.5 pl-4 text-[12.5px] text-text-secondary leading-[1.55] marker:text-[#10B981]">
            {c.top_strengths.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}

      {c.top_concerns.length > 0 && (
        <div>
          <div className="mb-1 font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
            Concerns
          </div>
          <ul className="list-disc space-y-0.5 pl-4 text-[12.5px] text-text-secondary leading-[1.55] marker:text-[#B45309]">
            {c.top_concerns.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}

      <footer className="mt-auto flex items-start gap-2 border-border border-t pt-3">
        <ArrowRight strokeWidth={1.75} className="mt-0.5 h-3 w-3 shrink-0 text-text-muted" />
        <p className="text-[12.5px] text-text-primary leading-[1.5]">{c.recommendation}</p>
      </footer>
    </article>
  );
}

function HeroRecommendation({
  id,
  packet,
  verdictStyle,
}: {
  id: string;
  packet: DebriefPacket;
  verdictStyle: (typeof VERDICT_STYLE)[DebriefVerdict];
}) {
  return (
    <section
      id={id}
      className={cn(
        'rounded-[16px] border px-5 py-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]',
        verdictStyle.border,
        verdictStyle.bg,
      )}
    >
      <div
        className={cn(
          'mb-1.5 font-mono text-[10.5px] uppercase tracking-[0.18em]',
          verdictStyle.text,
        )}
      >
        Agent recommendation · confidence {packet.confidence}
      </div>
      <p className="font-display text-[20px] text-text-primary leading-[1.4] tracking-[-0.005em]">
        {packet.headline_recommendation}
      </p>
    </section>
  );
}

function Themes({ id, themes }: { id: string; themes: DebriefTheme[] }) {
  if (themes.length === 0) return null;
  const sorted = [...themes].sort((a, b) => b.weight - a.weight);
  return (
    <section
      id={id}
      className="rounded-[16px] border border-border bg-white px-5 py-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
    >
      <header className="mb-3 flex items-center gap-2">
        <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5 text-cortex-600" />
        <h3 className="font-display text-[18px] text-text-primary leading-tight tracking-[-0.005em]">
          Themes across the panel
        </h3>
      </header>
      <ul className="flex flex-wrap gap-2">
        {sorted.map((t) => {
          const cls =
            t.tone === 'pos'
              ? 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]'
              : t.tone === 'neg'
                ? 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]'
                : 'border-border bg-surface text-text-secondary';
          return (
            <li key={t.label}>
              <span
                className={cn(
                  'inline-flex items-center gap-2 rounded-full border px-3 py-1 font-medium font-sans text-[12px]',
                  cls,
                )}
              >
                {t.label}
                <span className="font-mono text-[10px] opacity-70">
                  {t.evidence_count} signal{t.evidence_count === 1 ? '' : 's'}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function PanelGrid({ id, packet }: { id: string; packet: DebriefPacket }) {
  const panelists = packet.panel_members;
  if (panelists.length === 0) return null;
  return (
    <section
      id={id}
      className="overflow-hidden rounded-[16px] border border-border bg-white shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
    >
      <header className="flex items-center justify-between border-border border-b px-5 py-3">
        <div className="flex items-center gap-2">
          <Users strokeWidth={1.75} className="h-3.5 w-3.5 text-text-muted" />
          <h3 className="font-display text-[18px] text-text-primary leading-tight tracking-[-0.005em]">
            Panel votes
          </h3>
        </div>
        <span className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]">
          Votes mapped back to each candidate
        </span>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="bg-surface/60 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              <th className="sticky left-0 z-10 min-w-[200px] bg-surface/60 px-4 py-2.5">
                Panelist
              </th>
              {packet.candidates.map((c) => (
                <th
                  key={c.candidate_id}
                  scope="col"
                  className="min-w-[150px] px-4 py-2.5 text-center"
                >
                  {c.name.split(' ')[0]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {panelists.map((p) => (
              <tr key={p.name}>
                <td className="sticky left-0 z-10 bg-white px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full font-medium font-mono text-[10px] text-text-primary"
                      style={{ background: p.color, color: pickAvatarFg(p.color) }}
                    >
                      {p.initials}
                    </span>
                    <div className="min-w-0">
                      <div className="truncate font-medium text-[12.5px] text-text-primary">
                        {p.name}
                      </div>
                      <div className="truncate font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
                        {p.role}
                      </div>
                    </div>
                  </div>
                </td>
                {packet.candidates.map((c) => {
                  const vote = c.panel_votes.find((v) => v.panelist === p.name);
                  if (!vote) {
                    return (
                      <td key={c.candidate_id} className="px-4 py-3 text-center">
                        <span className="font-mono text-[11px] text-text-faint">—</span>
                      </td>
                    );
                  }
                  const style = VOTE_STYLE[vote.vote];
                  return (
                    <td key={c.candidate_id} className="px-4 py-3 text-center">
                      <span
                        className={cn(
                          'inline-flex items-center rounded-full px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em]',
                          style.bg,
                          style.text,
                        )}
                      >
                        {style.label}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RiskList({ id, risks }: { id: string; risks: string[] }) {
  if (risks.length === 0) return null;
  return (
    <section id={id} className="rounded-[16px] border border-[#FDE68A] bg-[#FFFBEB] px-5 py-4">
      <header className="mb-2 flex items-center gap-2">
        <AlertTriangle strokeWidth={1.75} className="h-3.5 w-3.5 text-[#B45309]" />
        <h3 className="font-display text-[18px] text-text-primary leading-tight tracking-[-0.005em]">
          Risks to watch
        </h3>
      </header>
      <ul className="flex flex-col gap-2">
        {risks.map((r) => (
          <li
            key={r}
            className="flex items-start gap-2 text-[13px] text-text-secondary leading-[1.55]"
          >
            <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[#F59E0B]" />
            {r}
          </li>
        ))}
      </ul>
    </section>
  );
}

function NextSteps({
  id,
  steps,
}: {
  id: string;
  steps: Array<{ label: string; owner?: string; due?: string }>;
}) {
  if (steps.length === 0) return null;
  return (
    <section
      id={id}
      className="rounded-[16px] border border-border bg-white px-5 py-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
    >
      <header className="mb-3 flex items-center gap-2">
        <ArrowRight strokeWidth={1.75} className="h-3.5 w-3.5 text-text-muted" />
        <h3 className="font-display text-[18px] text-text-primary leading-tight tracking-[-0.005em]">
          Next steps
        </h3>
      </header>
      <ul className="flex flex-col gap-2">
        {steps.map((s) => (
          <li
            key={s.label}
            className="flex flex-wrap items-center justify-between gap-2 rounded-[12px] border border-border bg-surface/40 px-3 py-2"
          >
            <span className="text-[13px] text-text-primary">{s.label}</span>
            <div className="flex items-center gap-3 font-mono text-[10px] text-text-muted uppercase tracking-[0.14em]">
              {s.owner && <span>{s.owner}</span>}
              {s.due && (
                <span>
                  Due{' '}
                  {new Date(s.due).toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                  })}
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
