'use client';

import { ArrowRight, FileText, Sparkles, Users, Wand2 } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import type { Requisition } from '@/domain';
import {
  type DebriefPacket,
  type DebriefVerdict,
  getDebriefPackets,
} from '@/fixtures/debrief-packets';
import { useDebriefInsights } from '@/hooks/use-services';
import { getPacket, listPackets, type PacketListItem } from '@/lib/debrief/api';
import { isV2ApiEnabled } from '@/lib/env';
import { relativeTimeFrom } from '@/lib/relative-time';
import { cn, pickAvatarFg } from '@/lib/utils';
import { DebriefPacketDrawer } from './debrief-packet-drawer';

interface DebriefTabProps {
  id: string;
  role: Requisition;
}

/**
 * A unified, thin "row" the list renders from EITHER source: the v2 packet-list
 * endpoint (thin `PacketListItem`) or a full fixture `DebriefPacket` (mock).
 * The full packet body is fetched on open (v2) or already in hand (mock).
 */
export interface PacketRow {
  id: string;
  verdict: DebriefVerdict | null;
  // Unifies the v2 list-item statuses with the mock packet's status, which now
  // includes 'draft' (the generate->preview state). Only `=== 'superseded'` is
  // branched on below, so 'draft' simply renders no badge.
  status: PacketListStatus | DebriefPacket['status'];
  candidateCount: number;
  generatedAt: string;
  title: string;
  subtitle: string | null;
  headline: string | null;
  /** Full packet when already in hand (mock path); null until fetched (v2). */
  full: DebriefPacket | null;
}

type PacketListStatus = PacketListItem['status'];

function rowFromListItem(item: PacketListItem): PacketRow {
  return {
    id: item.packet_id,
    verdict: item.verdict,
    status: item.status,
    candidateCount: item.candidate_ids.length,
    generatedAt: item.generated_at ?? item.created_at,
    title: 'Debrief packet',
    subtitle: null,
    headline: null,
    full: null,
  };
}

function rowFromPacket(p: DebriefPacket): PacketRow {
  return {
    id: p.id,
    verdict: p.verdict,
    status: p.status,
    candidateCount: p.candidates.length,
    generatedAt: p.generated_at,
    title: p.title,
    subtitle: p.subtitle,
    headline: p.headline_recommendation,
    full: p,
  };
}

const VERDICT_CHIP: Record<
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

export function DebriefTab({ id, role }: DebriefTabProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const deepLinkPacketId = searchParams?.get('debrief') ?? null;
  const { data: insights } = useDebriefInsights(role.id);

  // Real packet rows (v2) or fixture-derived rows (mock), newest first.
  const [rows, setRows] = useState<PacketRow[]>(() =>
    isV2ApiEnabled()
      ? []
      : [...getDebriefPackets(role.id)]
          .sort((a, b) => new Date(b.generated_at).getTime() - new Date(a.generated_at).getTime())
          .map(rowFromPacket),
  );

  useEffect(() => {
    if (!isV2ApiEnabled()) return;
    let active = true;
    listPackets(role.id)
      .then((items) => {
        if (active) setRows(items.map(rowFromListItem));
      })
      .catch(() => {
        // Surface as an empty list rather than crashing the tab; the lane copy
        // already explains the empty state.
        if (active) setRows([]);
      });
    return () => {
      active = false;
    };
  }, [role.id]);

  const [openPacketId, setOpenPacketId] = useState<string | null>(null);
  // The full packet for the open drawer. Mock rows carry it inline; v2 rows
  // fetch it on open.
  const [activePacket, setActivePacket] = useState<DebriefPacket | null>(null);

  const openPacket = useCallback(
    async (rowId: string) => {
      setOpenPacketId(rowId);
      const row = rows.find((r) => r.id === rowId);
      if (row?.full) {
        setActivePacket(row.full);
        return;
      }
      if (!isV2ApiEnabled()) return;
      try {
        const packet = await getPacket(rowId);
        setActivePacket(packet);
      } catch {
        // A still-generating/failed packet 404s — close the drawer.
        setActivePacket(null);
        setOpenPacketId(null);
      }
    },
    [rows],
  );

  const closeDrawer = useCallback(() => {
    setOpenPacketId(null);
    setActivePacket(null);
  }, []);

  useEffect(() => {
    if (!deepLinkPacketId) return;
    if (rows.some((r) => r.id === deepLinkPacketId)) {
      void openPacket(deepLinkPacketId);
    }
  }, [deepLinkPacketId, rows, openPacket]);

  const latest = rows[0] ?? null;

  const onGenerate = () => {
    // Carry the role TITLE alongside the id so the agent canvas can resolve the
    // display label from the query param (real prod role ids have no fixture).
    router.push(
      `/debrief?role=${encodeURIComponent(role.id)}&title=${encodeURIComponent(role.role_title)}`,
    );
  };

  return (
    <div id={id} className="flex flex-col gap-5">
      <AgentLane
        id={`${id}-lane`}
        role={role}
        latest={latest}
        insightSummary={insights?.summary ?? null}
        onGenerate={onGenerate}
      />

      <section id={`${id}-packets`} aria-label="Debrief packets">
        <header className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="font-display text-[22px] text-text-primary leading-tight tracking-[-0.01em]">
              Debrief packets
            </h2>
            <p className="mt-0.5 text-[12.5px] text-text-muted">
              Role-level artifacts the debrief agent drops each time the loop reaches a decision
              moment. Each packet compares candidates, surfaces themes, and recommends next steps.
            </p>
          </div>
          {rows.length > 0 && (
            <span className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]">
              {rows.length} packet{rows.length === 1 ? '' : 's'} in this role
            </span>
          )}
        </header>

        {rows.length === 0 ? (
          <EmptyState id={`${id}-empty`} onGenerate={onGenerate} />
        ) : (
          <ul id={`${id}-packets-list`} className="flex flex-col gap-3">
            {rows.map((r) => (
              <PacketCard
                key={r.id}
                id={`${id}-packet-${r.id}`}
                row={r}
                onOpen={() => void openPacket(r.id)}
              />
            ))}
          </ul>
        )}
      </section>

      {openPacketId && activePacket && (
        <DebriefPacketDrawer id={`${id}-drawer`} packet={activePacket} onClose={closeDrawer} />
      )}
    </div>
  );
}

function AgentLane({
  id,
  role,
  latest,
  insightSummary,
  onGenerate,
}: {
  id: string;
  role: Requisition;
  latest: PacketRow | null;
  insightSummary: string | null;
  onGenerate: () => void;
}) {
  return (
    <section
      id={id}
      className="relative overflow-hidden rounded-[18px] border border-cortex-100 bg-cortex-50 px-5 py-5"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -top-12 -right-12 h-40 w-40 rounded-full bg-white/50 blur-3xl"
      />
      <div className="relative flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-[680px]">
          <div className="mb-2 flex items-center gap-2 font-mono text-[10.5px] text-cortex-600 uppercase tracking-[0.18em]">
            <span
              aria-hidden
              className="flex h-5 w-5 items-center justify-center rounded-full bg-white/70"
            >
              <Sparkles strokeWidth={1.75} className="h-3 w-3 text-cortex-600" />
            </span>
            Debrief agent · {role.role_title}
          </div>
          <p className="font-display text-[22px] text-text-primary leading-[1.35] tracking-[-0.005em]">
            {latest?.headline
              ? latest.headline
              : insightSummary
                ? insightSummary
                : 'The debrief agent will compare candidates the moment you have two or more loops in flight.'}
          </p>
          {latest && (
            <div className="mt-3 flex flex-wrap items-center gap-3 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              <span>Latest: {latest.title}</span>
              <span aria-hidden>·</span>
              <span>Generated {relativeTimeFrom(latest.generatedAt)}</span>
              <span aria-hidden>·</span>
              <span>
                {latest.candidateCount} candidate
                {latest.candidateCount === 1 ? '' : 's'} compared
              </span>
            </div>
          )}
        </div>
        <button
          id={`${id}-generate`}
          type="button"
          onClick={onGenerate}
          className="inline-flex items-center gap-2 rounded-full border border-text-primary bg-text-primary px-4 py-2 font-medium font-sans text-[13px] text-white transition-colors hover:bg-[#222]"
          title="Open the Debrief agent with this role pre-selected"
        >
          <Wand2 strokeWidth={1.75} className="h-4 w-4" />
          Generate new debrief packet in agent
          <ArrowRight strokeWidth={1.75} className="h-3.5 w-3.5" />
        </button>
      </div>
    </section>
  );
}

function EmptyState({ id, onGenerate }: { id: string; onGenerate: () => void }) {
  return (
    <div
      id={id}
      className="flex flex-col items-center justify-center rounded-[16px] border border-border border-dashed bg-white px-8 py-14 text-center"
    >
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-surface text-text-muted">
        <FileText strokeWidth={1.75} className="h-4 w-4" />
      </div>
      <p className="text-[13.5px] text-text-primary">No debrief packets yet.</p>
      <p className="mt-1 max-w-md text-[12.5px] text-text-muted leading-[1.5]">
        Head into the Debrief agent to compare candidates — the artifact it ships will land here,
        ready to open, share, and export.
      </p>
      <button
        type="button"
        onClick={onGenerate}
        className="mt-4 inline-flex items-center gap-2 rounded-full border border-text-primary bg-text-primary px-4 py-2 font-medium font-sans text-[12.5px] text-white hover:bg-[#222]"
      >
        <Wand2 strokeWidth={1.75} className="h-3.5 w-3.5" />
        Generate new debrief packet in agent
        <ArrowRight strokeWidth={1.75} className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

export function PacketCard({
  id,
  row,
  onOpen,
}: {
  id: string;
  row: PacketRow;
  onOpen: () => void;
}) {
  const packet = row.full;
  const verdict = row.verdict ? VERDICT_CHIP[row.verdict] : null;
  // Rich avatars/per-candidate chips only when we hold the full packet (mock or
  // already-fetched). Thin v2 rows degrade to a candidate count.
  const avatars = packet ? packet.candidates.slice(0, 5) : [];
  const rest = packet ? packet.candidates.length - avatars.length : 0;
  const panelistCount = packet?.panel_members.length ?? 0;

  return (
    <li
      id={id}
      className="group relative overflow-hidden rounded-[16px] border border-border bg-white shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-shadow hover:border-text-primary/40 hover:shadow-[0_4px_16px_rgba(0,0,0,0.06)]"
    >
      <button
        id={`${id}-open`}
        type="button"
        onClick={onOpen}
        aria-label={`Open debrief packet: ${row.title}`}
        className="absolute inset-0 z-10 cursor-pointer"
      />
      <div className="pointer-events-none relative z-20 flex flex-col gap-4 p-5">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]">
              <span
                aria-hidden
                className="flex h-4 w-4 items-center justify-center rounded-full bg-cortex-50 text-cortex-600"
              >
                <Sparkles strokeWidth={2} className="h-2.5 w-2.5" />
              </span>
              Debrief packet
              <span aria-hidden>·</span>
              <span>{relativeTimeFrom(row.generatedAt)}</span>
              {row.status === 'superseded' && (
                <span className="rounded-full border border-border bg-surface px-2 py-0.5 text-[9.5px] text-text-muted normal-case tracking-normal">
                  superseded
                </span>
              )}
            </div>
            <h3 className="mt-1.5 font-display text-[22px] text-text-primary leading-tight tracking-[-0.01em]">
              {row.title}
            </h3>
            {row.subtitle && (
              <p className="mt-1 text-[13px] text-text-secondary leading-[1.5]">{row.subtitle}</p>
            )}
          </div>
          {verdict && (
            <div className="pointer-events-auto relative z-30 flex shrink-0 items-center gap-1.5">
              <span
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-medium font-sans text-[12px]',
                  verdict.border,
                  verdict.bg,
                  verdict.text,
                )}
              >
                <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', verdict.dot)} />
                {verdict.label}
              </span>
            </div>
          )}
        </header>

        <div className="flex flex-wrap items-center gap-3">
          {avatars.length > 0 && (
            <div className="flex items-center">
              {avatars.map((c, i) => (
                <span
                  key={c.candidate_id}
                  aria-hidden
                  className={cn(
                    'flex h-7 w-7 items-center justify-center rounded-full border-2 border-white font-medium font-mono text-[10px] text-text-primary',
                    i > 0 && '-ml-2',
                  )}
                  style={{ background: c.color, color: pickAvatarFg(c.color) }}
                  title={c.name}
                >
                  {c.initials}
                </span>
              ))}
              {rest > 0 && (
                <span
                  aria-hidden
                  className="-ml-2 flex h-7 w-7 items-center justify-center rounded-full border-2 border-white bg-surface font-mono text-[10px] text-text-muted"
                >
                  +{rest}
                </span>
              )}
            </div>
          )}
          <span className="inline-flex items-center gap-1 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
            <Users strokeWidth={1.75} className="h-3 w-3" />
            {row.candidateCount} candidate{row.candidateCount === 1 ? '' : 's'}
            {panelistCount > 0 ? ` · ${panelistCount} panelists` : ''}
          </span>
          <span className="ml-auto inline-flex items-center gap-1.5 font-medium font-sans text-[12px] text-text-primary transition-transform group-hover:translate-x-0.5">
            Open packet
            <ArrowRight strokeWidth={1.75} className="h-3.5 w-3.5" />
          </span>
        </div>

        {row.headline && (
          <p className="rounded-[12px] border border-border bg-surface/40 px-3 py-2.5 text-[12.5px] text-text-secondary leading-[1.5]">
            {row.headline}
          </p>
        )}

        {packet && (
          <div className="flex flex-wrap gap-1.5">
            {packet.candidates.map((c) => {
              const style = VERDICT_CHIP[c.verdict];
              return (
                <span
                  key={c.candidate_id}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em]',
                    style.border,
                    style.bg,
                    style.text,
                  )}
                  title={`${c.name} · ${style.label}`}
                >
                  <span aria-hidden className={cn('h-1 w-1 rounded-full', style.dot)} />
                  {c.name.split(' ')[0]}
                </span>
              );
            })}
          </div>
        )}
      </div>
    </li>
  );
}
