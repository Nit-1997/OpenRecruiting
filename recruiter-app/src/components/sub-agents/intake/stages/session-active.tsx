'use client';

import { useModalitySwitch } from '@/hooks/intake/use-modality-switch';
import { useSubmitIntake } from '@/hooks/intake/use-submit-intake';
import { useIntakeStore } from '@/stores/intake-store';
import type { IntakeSession } from '@/types/intake';
import { CoverageTable } from '../components/coverage-table';
import { ModalityConflictToast } from '../components/modality-conflict-toast';
import { SessionConversationPanel } from '../components/session-conversation-panel';
import { SubmitConfirmModal } from '../components/submit-confirm-modal';
import { SessionShell } from '../overlay/SessionShell';
import { SessionTopBar } from '../overlay/SessionTopBar';

interface Props {
  session: IntakeSession;
  mode: 'text' | 'voice';
}

// Single stage for BOTH text_active and voice_active. The canvas renders this
// one component type for both stages, so flipping modality re-renders in place
// (changing `mode`) instead of unmounting one stage and mounting another. That,
// plus the persistent transcript in SessionConversationPanel, removes the
// white-flash + lost-messages on handoff.
export function SessionActiveStage({ session, mode }: Props) {
  const { switchTo } = useModalitySwitch();
  const setPendingTransition = useIntakeStore((s) => s.setPendingTransition);
  const { confirmOpen, setConfirmOpen, submitting, submittingError, submit } =
    useSubmitIntake(session);

  // text→voice: optimistic flip so the canvas shows voice immediately (the panel
  // then shows the dimmed transcript + "Connecting voice…") while /switch runs.
  const handleSwitchToVoice = (): void => {
    setPendingTransition('voice_active', 60_000);
    void switchTo('voice');
  };

  const gridId = mode === 'voice' ? 'v2-intake-stage-voice-active' : 'v2-intake-stage-text-active';

  return (
    <SessionShell
      topBar={
        <SessionTopBar
          session={session}
          onSubmit={() => setConfirmOpen(true)}
          submitLabel="Submit intake"
        />
      }
      body={
        <>
          <div id={gridId} data-testid={gridId} className="mz-session mz-session-centered">
            <aside id={`${gridId}-conv`} className="mz-col-conv">
              <SessionConversationPanel
                session={session}
                mode={mode}
                onSwitchToVoice={handleSwitchToVoice}
              />
            </aside>
            <main id={`${gridId}-hero`} className="mz-col-hero">
              <CoverageTable session={session} />
            </main>
          </div>
          <ModalityConflictToast />
          {confirmOpen && (
            <SubmitConfirmModal
              id={`v2-intake-${mode}-submit-confirm`}
              session={session}
              submitting={submitting}
              errorMessage={submittingError}
              onConfirm={() => void submit()}
              onClose={() => setConfirmOpen(false)}
            />
          )}
        </>
      }
    />
  );
}
