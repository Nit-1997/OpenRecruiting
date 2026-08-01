'use client';

import { ArrowUp, Loader2, Mic } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';
import { submitBrainInput } from '@/components/sub-agents/brain/flow';
import { submitDebriefMessage } from '@/components/sub-agents/debrief/flow';
import {
  submitQuery as sourcingSubmitQuery,
  submitSourcingInput,
  submitSourcingPreferences,
} from '@/components/sub-agents/sourcing/flow';
import { STAGE_FALLBACK } from '@/fixtures/stage-fallback';
import { useSpeechToText } from '@/hooks/use-speech-to-text';
import { routeHomeChip } from '@/lib/home-route';
import { makeMessage } from '@/lib/sub-agent-runner';
import { cn } from '@/lib/utils';
import { type AssistantIntent, classifyAssistantIntent } from '@/services/assistant';
import type { ComposerScope } from '@/stores';
import { useComposerStore, useSessionStore, useShellStore } from '@/stores';

interface ComposerProps {
  id: string;
}

function placeholderFor(scope: ComposerScope, stage: string | null | undefined): string {
  if (scope.kind === 'home') return 'Ask OpenRecruiting anything — or press ⌘K';
  if (scope.kind === 'qna') return 'Ask about this view…';
  if (scope.kind === 'agentic') {
    if (scope.tabId === 'intake') {
      switch (stage) {
        case 'mode_choice':
          return 'How do you want to kick off this role?';
        case 'intake_chat':
          return 'Reply to keep shaping the role…';
        case 'intake_voice':
          return 'Say something — the mic is live.';
        case 'intake_upload':
          return 'Drop a JD above, or describe the role.';
        case 'requisition_live':
          return 'Edit anything — swap rounds, tweak level, publish.';
        case 'scorecard_edit':
          return 'Re-order, swap, or rewrite any question.';
        case 'publish':
          return 'Say the word and I ship it.';
        default:
          return 'Type a message, upload a JD, or tap the mic…';
      }
    }
    if (scope.tabId === 'debrief') {
      switch (stage) {
        case 'role_pick':
          return 'Pick a role above — or type a role name.';
        case 'candidate_pick':
          return 'Say the candidate names, or pick below.';
        case 'analyzing':
          return 'Almost there — pulling signal now…';
        case 'result':
          return 'Push back on any score, or ask me why.';
        default:
          return 'Ask OpenRecruiting to debrief candidates…';
      }
    }
    if (scope.tabId === 'sourcing') {
      switch (stage) {
        case 'mode_pick':
          return 'Pick an existing role or start fresh…';
        case 'role_pick':
          return 'Pick a role above — or type a role name.';
        case 'query_build':
          return 'Describe the candidate in plain English…';
        case 'preferences_chat':
          return 'Any target companies, exclusions, or outreach voice?';
        case 'strategy_publish':
        case 'channel_stream':
        case 'candidate_stream':
          return 'OpenRecruiting is working — hang tight…';
        case 'offer_add':
          return 'Pick the candidates to add, or ask a follow-up…';
        case 'results':
          return 'Refine filters, add to pipeline, or send outreach.';
        default:
          return 'Ask OpenRecruiting to source candidates…';
      }
    }
    if (scope.tabId === 'brain') {
      switch (stage) {
        case 'brain':
          return 'Ask OpenRecruiting Brain — drill a node, explain a story, mute a signal…';
        default:
          return 'Ask OpenRecruiting Brain anything about your pipeline…';
      }
    }
    return 'Type a message, upload a JD, or tap the mic…';
  }
  return '';
}

const OUT_OF_SCOPE_CHIPS = [
  { label: 'Browse open roles', value: '/view/roles', primary: true },
  { label: 'Start an intake call', value: 'intake' },
];

export function Composer({ id }: ComposerProps) {
  const router = useRouter();
  const mode = useShellStore((s) => s.mode());
  const scope = useComposerStore((s) => s.scope);
  const value = useComposerStore((s) => s.value);
  const setValue = useComposerStore((s) => s.setValue);
  const clearValue = useComposerStore((s) => s.clearValue);
  const activeTabId = useShellStore((s) => s.activeTabId);
  const session = useSessionStore((s) => (activeTabId ? s.sessions[activeTabId] : null));
  const stage = session?.stage ?? null;
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [classifying, setClassifying] = useState(false);
  const {
    isListening,
    error: micError,
    startListening,
    stopListening,
  } = useSpeechToText({
    onTranscript: (transcript, isFinal) => {
      if (!isFinal || !transcript) return;
      const cur = useComposerStore.getState().value;
      setValue(cur ? `${cur} ${transcript}`.trim() : transcript.trim());
    },
  });
  if (mode === 'qna') return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const currentValue = useComposerStore.getState().value;
    const currentScope = useComposerStore.getState().scope;
    // Read the active session's stage fresh from the store (not the render-time
    // closure `stage`) so stage-gated routing keys off the latest state even if
    // the submit fires before a stage-changing re-render has flushed.
    const currentStage =
      currentScope.kind === 'agentic'
        ? (useSessionStore.getState().sessions[currentScope.tabId]?.stage ?? null)
        : stage;
    const trimmed = currentValue.trim();
    if (!trimmed) return;
    clearValue();

    if (currentScope.kind === 'home') {
      const sessions = useSessionStore.getState();
      if (!sessions.sessions.home) sessions.startSession('home', 'active');
      sessions.appendMessage('home', makeMessage('user', trimmed, 'text', 'chat'));

      setClassifying(true);
      let intent: AssistantIntent;
      try {
        intent = await classifyAssistantIntent(trimmed);
      } finally {
        setClassifying(false);
      }

      if (intent === 'intake_call') {
        routeHomeChip('intake', trimmed);
        router.push('/intake');
        return;
      }
      if (intent === 'browse_roles') {
        router.push('/view/roles');
        return;
      }
      // out_of_scope (and any classify failure, which fails open to out_of_scope):
      // offer the two live flows as routing chips.
      useSessionStore
        .getState()
        .appendMessage(
          'home',
          makeMessage(
            'agent',
            "I can't do that yet — here's what I can help with right now:",
            'text',
            'chat',
            OUT_OF_SCOPE_CHIPS,
          ),
        );
      return;
    }

    if (currentScope.kind !== 'agentic') return;

    // Intake is driven by the deterministic Hub (its own modal + lists), not the
    // global composer — typing here is a no-op on the intake surface.
    if (currentScope.tabId === 'intake') {
      return;
    }

    if (currentScope.tabId === 'sourcing') {
      if (currentStage === 'query_build') {
        await sourcingSubmitQuery(trimmed);
        return;
      }
      if (currentStage === 'preferences_chat') {
        await submitSourcingPreferences(trimmed);
        return;
      }
      if (currentStage === 'results') {
        await submitSourcingInput(trimmed);
        return;
      }
      const sessions = useSessionStore.getState();
      sessions.appendMessage(currentScope.tabId, makeMessage('user', trimmed, 'text', 'chat'));
      const perTab = STAGE_FALLBACK[currentScope.tabId] ?? STAGE_FALLBACK.default;
      const reply = perTab[currentStage ?? 'default'] ?? perTab.default;
      sessions.appendMessage(
        currentScope.tabId,
        makeMessage('agent', reply.text, 'text', 'chat', reply.chips),
      );
      return;
    }

    if (currentScope.tabId === 'brain') {
      await submitBrainInput(trimmed);
      return;
    }

    // Debrief: once a packet exists (the `result` stage), the composer becomes
    // the chat-over-the-packet entry point — route to the SSE conversation
    // agent instead of the canned fallback. Non-`result` stages (role_pick /
    // candidate_pick / analyzing) keep their deterministic Hub behavior below.
    if (currentScope.tabId === 'debrief' && currentStage === 'result') {
      await submitDebriefMessage(trimmed);
      return;
    }

    // Other sub-agents: user msg + canned fallback reply.
    const sessions = useSessionStore.getState();
    if (!sessions.sessions[currentScope.tabId]) {
      sessions.startSession(currentScope.tabId, 'stub');
    }
    sessions.appendMessage(currentScope.tabId, makeMessage('user', trimmed, 'text', 'chat'));
    const perTab = STAGE_FALLBACK[currentScope.tabId] ?? STAGE_FALLBACK.default;
    const reply = perTab[currentStage ?? 'default'] ?? perTab.default;
    sessions.appendMessage(
      currentScope.tabId,
      makeMessage('agent', reply.text, 'text', 'chat', reply.chips),
    );
  };

  const handleMicClick = () => {
    if (isListening) {
      stopListening();
      return;
    }
    void startListening();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !classifying) {
      e.preventDefault();
      void handleSubmit(e as unknown as React.FormEvent);
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  };

  return (
    <div id={id} className="w-full">
      <form
        id={`${id}-form`}
        aria-label="Composer"
        onSubmit={(e) => {
          void handleSubmit(e);
          if (textareaRef.current) textareaRef.current.style.height = 'auto';
        }}
        className="mx-auto flex max-w-[760px] flex-col gap-2 rounded-[22px] border border-border bg-white px-3 pt-2.5 pb-2 shadow-[0_8px_28px_rgba(0,0,0,0.06)] transition-colors focus-within:border-text-primary sm:px-4 sm:pt-3 sm:pb-2.5"
      >
        <textarea
          id={`${id}-input`}
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={placeholderFor(scope, stage)}
          rows={1}
          className="min-h-[24px] w-full resize-none border-0 bg-transparent font-sans text-[14.5px] text-text-primary leading-[1.5] placeholder:text-text-muted focus:outline-none"
        />
        <div id={`${id}-actions`} className="flex items-center justify-end">
          <div className="flex items-center gap-2">
            <button
              id={`${id}-mic`}
              type="button"
              aria-label="Voice to text"
              title="Voice to text"
              aria-pressed={isListening}
              onClick={handleMicClick}
              className={cn(
                'flex h-8 w-8 items-center justify-center rounded-full border bg-white transition-colors',
                isListening
                  ? 'border-red-500 text-red-500'
                  : 'border-border text-text-muted hover:border-text-primary hover:text-text-primary',
              )}
            >
              <Mic strokeWidth={1.75} className="h-4 w-4" />
            </button>
            <button
              id={`${id}-send`}
              type="submit"
              aria-label="Send"
              aria-busy={classifying}
              disabled={!value.trim() || classifying}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-text-primary text-white transition-colors hover:bg-[#222] disabled:cursor-not-allowed disabled:bg-text-muted/40"
            >
              {classifying ? (
                <Loader2 strokeWidth={1.75} className="h-4 w-4 animate-spin" />
              ) : (
                <ArrowUp strokeWidth={1.75} className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>
        {micError && (
          <p
            id={`${id}-mic-error`}
            role="status"
            aria-live="polite"
            className="px-1 font-sans text-[12px] text-red-500"
          >
            {micError}
          </p>
        )}
      </form>
    </div>
  );
}
