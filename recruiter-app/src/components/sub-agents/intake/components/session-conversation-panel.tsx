'use client';

import { Mic } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Orb } from '@/components/sub-agents/intake/primitives';
import { useTextStream } from '@/hooks/intake/use-text-stream';
import type { IntakeSession, Turn } from '@/types/intake';
import { type PendingUserTurn, shouldShowPending } from './text-chat-reconcile';
import { TextComposer } from './text-composer';
import { TextMessageList } from './text-message-list';
import { VoiceDock, type VoicePhase } from './voice-dock';

interface Props {
  session: IntakeSession;
  mode: 'text' | 'voice';
  onSwitchToVoice: () => void;
}

// One shared conversation panel for BOTH modalities. The transcript
// (TextMessageList) holds a stable position in the tree, so switching
// text↔voice never unmounts it — the messages stay on screen and only the
// header status + footer swap. This is what kills the white-flash + message
// loss on handoff. Voice hooks live in <VoiceDock>, mounted only in voice mode.
function conversationTurns(rawTurns: Turn[] | undefined): Turn[] {
  const out: Turn[] = [];
  for (const t of rawTurns ?? []) {
    if (!t || typeof t.idx !== 'number') continue;
    if (t.role !== 'user' && t.role !== 'assistant') continue;
    out.push(t);
  }
  out.sort((a, b) => a.idx - b.idx);
  return out;
}

export function SessionConversationPanel({ session, mode, onSwitchToVoice }: Props) {
  const isText = mode === 'text';
  const { status, streamingText, error, lastDone, send, open } = useTextStream(session.id);
  const turns = conversationTurns(session.turns);
  const lastTurn = turns.at(-1);
  const [voicePhase, setVoicePhase] = useState<VoicePhase>('idle');
  const [pending, setPending] = useState<PendingUserTurn | null>(null);

  // Floor rule (text only): the agent takes the floor when it owes a reply
  // (brand-new session or the recruiter spoke last). Fire once per owed reply.
  const agentOwesReply = turns.length === 0 || lastTurn?.role === 'user';
  const openedForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!isText) return;
    if (!agentOwesReply) return;
    if (status !== 'idle') return;
    if (session.active_modality === 'voice') return;
    const key = `${session.id}:${lastTurn?.idx ?? 'empty'}`;
    if (openedForRef.current === key) return;
    openedForRef.current = key;
    void open();
  }, [isText, session.id, agentOwesReply, status, session.active_modality, lastTurn?.idx, open]);

  // Optimistic user turn — render the recruiter's message instantly; reconcile
  // when the persisted turn lands, drop on rejection. Returns false when the
  // send was dropped/failed so the composer can restore the text (never lose it).
  const handleSend = async (message: string): Promise<boolean> => {
    const trimmed = message.trim();
    if (!trimmed) return false;
    setPending({ text: trimmed, baseMaxIdx: turns.at(-1)?.idx ?? -1 });
    const ok = await send(message);
    if (!ok) setPending(null);
    return ok;
  };
  useEffect(() => {
    if (!pending) return;
    if (!shouldShowPending(turns, pending)) {
      setPending(null);
      return;
    }
    if (status === 'error' || status === 'modality_conflict') setPending(null);
  }, [turns, pending, status]);

  const pendingUserText =
    isText && shouldShowPending(turns, pending) ? (pending?.text ?? null) : null;
  const committedIdx = lastDone?.assistant_turn_idx;
  const awaitingCommit =
    committedIdx != null && streamingText.length > 0 && !turns.some((t) => t.idx === committedIdx);
  const isStreaming = isText && (status === 'streaming' || awaitingCommit);
  const noAnimIdxs = lastDone != null ? [lastDone.user_turn_idx, lastDone.assistant_turn_idx] : [];

  const live = !isText && voicePhase === 'live';
  const connecting = !isText && voicePhase === 'connecting';
  const orbState = live ? 'listening' : connecting ? 'connecting' : 'idle';
  const statusLabel = isText
    ? 'Voice paused · chatting'
    : live
      ? 'Live · OpenRecruiting is listening'
      : connecting
        ? 'Connecting voice…'
        : voicePhase === 'error'
          ? 'Voice error'
          : 'Voice paused';

  const rootId = isText ? 'v2-intake-text-chat-panel' : 'v2-intake-voice-panel';

  return (
    <div id={rootId} data-testid={rootId} className="mz-conv-panel">
      <header className="mz-conv-top">
        <div className="mz-conv-orb">
          <div
            id={isText ? 'v2-intake-text-chat-panel-orb' : 'v2-intake-voice-panel-orb'}
            data-testid={isText ? undefined : 'v2-intake-voice-panel-orb'}
            style={isText ? { opacity: 0.55 } : undefined}
          >
            <Orb size={42} state={orbState} motion={live || connecting} />
          </div>
          <div>
            <div className="mz-conv-title">Intake conversation</div>
            <div
              id={isText ? 'v2-intake-text-chat-panel-status' : 'v2-intake-voice-panel-status'}
              className="mz-voice-status"
              style={{ margin: 0, color: live ? 'var(--periwinkle)' : 'var(--text-muted)' }}
            >
              <span
                className={live ? 'mz-live-dot mz-live-anim' : 'mz-live-dot'}
                style={live ? undefined : { background: 'var(--text-faint)' }}
              />
              {statusLabel}
            </div>
          </div>
        </div>
      </header>

      <div
        id={isText ? 'v2-intake-text-chat-panel-list-wrapper' : 'v2-intake-voice-panel-thread'}
        className="flex flex-col flex-1 min-h-0"
        style={{
          opacity: connecting ? 0.4 : 1,
          filter: connecting ? 'grayscale(0.4)' : 'none',
          transition: 'opacity 220ms ease, filter 220ms ease',
        }}
      >
        <TextMessageList
          turns={turns}
          streamingAssistantText={streamingText}
          isStreaming={isStreaming}
          pendingUserText={pendingUserText}
          noAnimIdxs={noAnimIdxs}
        />
      </div>

      {isText && error && (
        <div
          id="v2-intake-text-chat-panel-error"
          className="mx-4 mb-2 rounded-md px-3 py-2 text-xs"
          style={
            error.code === 'modality_conflict'
              ? {
                  border: '1px solid var(--status-warn-bd)',
                  background: 'var(--status-warn-bg)',
                  color: 'var(--status-warn-fg)',
                }
              : {
                  border: '1px solid var(--status-danger-bd)',
                  background: 'var(--status-danger-bg)',
                  color: 'var(--status-danger-fg)',
                }
          }
        >
          {error.message}
        </div>
      )}

      <footer className="mz-conv-foot">
        {isText ? (
          <>
            <div className="mz-conv-switch">
              <button
                id="v2-intake-text-chat-panel-switch-voice-btn"
                data-testid="v2-intake-stage-text-active-switch-voice-btn"
                type="button"
                className="mz-btn-switch mz-btn-switch-sm"
                onClick={onSwitchToVoice}
              >
                <Mic size={14} color="currentColor" />
                Switch to voice
              </button>
            </div>
            <TextComposer
              onSend={handleSend}
              disabled={isStreaming}
              placeholder={
                isStreaming
                  ? 'Agent is replying...'
                  : 'Type your reply… (Enter to send, Shift+Enter for newline)'
              }
            />
          </>
        ) : (
          <VoiceDock sessionId={session.id} hasTurns={turns.length > 0} onPhase={setVoicePhase} />
        )}
      </footer>
    </div>
  );
}
