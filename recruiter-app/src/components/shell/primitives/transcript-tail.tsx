'use client';

import { Fragment } from 'react';
import { ConfirmCard } from '@/components/sub-agents/debrief/confirm-card';
import {
  confirmDebriefAction,
  dismissDebriefAction,
  reopenDebriefPacket,
} from '@/components/sub-agents/debrief/flow';
import { DebriefPacketPill } from '@/components/sub-agents/debrief/packet-pill';
import { useSessionStore } from '@/stores';
import type { ChatTabId, Message } from '@/types';
import { type AgentChip, AgentMsg } from './agent-msg';
import { CortexMsg } from './cortex-msg';
import { CortexTrailMsg } from './cortex-trail-msg';
import { UserMsg } from './user-msg';

interface TranscriptTailProps {
  id: string;
  tabId: ChatTabId;
  onChip?: (chip: AgentChip) => void;
  /** Only render messages whose ts < until (ms). */
  until?: number;
  /** Only render messages whose ts >= since (ms). */
  since?: number;
  /**
   * When true, the first agent message renders as a normal chat bubble
   * instead of the serif "display" welcome. Use on routed/deep-link
   * entries where the greeting isn't a cold-start welcome.
   */
  skipDisplayFirst?: boolean;
}

function formatTime(ts: string): string {
  try {
    const time = new Date(ts).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
    });
    return `${dayLabel(ts)} · ${time}`;
  } catch {
    return '';
  }
}

function dayKey(ts: string): string {
  const d = new Date(ts);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function dayLabel(ts: string): string {
  const d = new Date(ts);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (dayKey(ts) === dayKey(today.toISOString())) return 'Today';
  if (dayKey(ts) === dayKey(yesterday.toISOString())) return 'Yesterday';
  return d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
}

export function TranscriptTail({
  id,
  tabId,
  onChip,
  until,
  since,
  skipDisplayFirst = false,
}: TranscriptTailProps) {
  const session = useSessionStore((s) => s.sessions[tabId]);
  if (!session) return null;
  const chatMsgs: Message[] = session.messages
    .filter((m) => {
      const ms = Date.parse(m.ts);
      if (Number.isNaN(ms)) return true;
      if (until !== undefined && ms >= until) return false;
      if (since !== undefined && ms < since) return false;
      return true;
    })
    // Some flows (home → intake chip routing) seed a user message with a ts
    // intentionally earlier than the stage greeting's ts, so the user's
    // original intent shows up above the agent's reaction. Sort by ts here
    // so render order follows the timeline regardless of insertion order.
    .slice()
    .sort((a, b) => {
      const am = Date.parse(a.ts);
      const bm = Date.parse(b.ts);
      if (Number.isNaN(am) || Number.isNaN(bm)) return 0;
      return am - bm;
    });
  if (chatMsgs.length === 0) return null;

  // Identify the first agent message so it renders in the display variant
  // (serif welcome heading) while the rest stay as small chat bubbles.
  // Deep-link entries pass skipDisplayFirst to keep the greeting as a normal
  // chat bubble — the serif treatment is reserved for cold-start welcomes.
  const firstAgentId = skipDisplayFirst
    ? null
    : (chatMsgs.find((m) => m.role === 'agent')?.id ?? null);

  let lastDay: string | null = null;

  return (
    <div id={id} className="flex flex-col gap-3.5 pt-2">
      {chatMsgs.map((m) => {
        const thisDay = dayKey(m.ts);
        const showDivider = thisDay !== lastDay;
        lastDay = thisDay;

        const divider = showDivider ? (
          <div
            id={`${id}-day-${m.id}`}
            className="flex items-center justify-center gap-3 py-3 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.22em]"
          >
            <span className="h-px flex-1 bg-border" />
            <span>{dayLabel(m.ts)}</span>
            <span className="h-px flex-1 bg-border" />
          </div>
        ) : null;

        const isFirstAgent = m.role === 'agent' && m.id === firstAgentId;

        const body =
          m.role === 'user' ? (
            <UserMsg
              id={`${id}-m-${m.id}`}
              text={m.text}
              mode={m.mode ?? 'text'}
              time={formatTime(m.ts)}
            />
          ) : m.packetRef ? (
            <DebriefPacketPill
              id={`${id}-m-${m.id}`}
              roleTitle={m.packetRef.roleTitle}
              time={formatTime(m.ts)}
              onOpen={() => {
                if (m.packetRef) void reopenDebriefPacket(m.packetRef);
              }}
            />
          ) : m.confirmAction ? (
            <ConfirmCard
              id={`${id}-m-${m.id}`}
              action={m.confirmAction}
              status={m.confirmStatus ?? 'pending'}
              time={formatTime(m.ts)}
              onConfirm={() => {
                void confirmDebriefAction(m.id);
              }}
              onDismiss={() => {
                dismissDebriefAction(m.id);
              }}
            />
          ) : m.cortexTrail ? (
            <CortexTrailMsg
              id={`${id}-m-${m.id}`}
              artifactId={m.cortexTrail.artifactId}
              time={formatTime(m.ts)}
            />
          ) : m.cortex ? (
            <CortexMsg
              id={`${id}-m-${m.id}`}
              payload={m.cortex}
              time={formatTime(m.ts)}
              {...(onChip ? { onChip } : {})}
            />
          ) : (
            <AgentMsg
              id={`${id}-m-${m.id}`}
              variant={isFirstAgent ? 'display' : 'small'}
              time={formatTime(m.ts)}
              showMeta={!isFirstAgent}
              {...(m.sub ? { sub: m.sub } : {})}
              {...(m.chips ? { chips: m.chips } : {})}
              {...(onChip ? { onChip } : {})}
            >
              {m.text}
            </AgentMsg>
          );

        return (
          <Fragment key={m.id}>
            {divider}
            {body}
          </Fragment>
        );
      })}
    </div>
  );
}
