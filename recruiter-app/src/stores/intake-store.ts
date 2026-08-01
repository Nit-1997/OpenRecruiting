import { create } from 'zustand';
import type { CurrentAnswers, IntakeModality, IntakeStage } from '@/types/intake';

interface PendingTransition {
  to: IntakeStage;
  expiresAt: number;
}

interface PendingModality {
  to: IntakeModality;
  expiresAt: number;
}

type SwitchError =
  | { type: 'conflict'; held: IntakeModality; requested: IntakeModality; message: string }
  | { type: 'drain_failed'; message: string; innerError?: string }
  | { type: 'generic'; message: string };

type ReprocessError =
  | { type: 'already_running'; message: string }
  | { type: 'lambda_failed'; message: string }
  | { type: 'generic'; message: string };

interface IntakeStoreState {
  sessionId: string | null;
  pendingTransition: PendingTransition | null;
  error: string | null;

  // Set when the user explicitly ends the conversation ("End chat"). This is
  // the ONLY signal that moves an in-progress session to the wrapping/submit
  // screen — deriveStage must never infer completion from a null modality lock.
  endedSessionId: string | null;
  setEndedSession: (id: string | null) => void;

  // Set when the user opens a PUBLISHED role from the Hub's "Edit existing"
  // list. deriveStage forces 'published' for published sessions; this signal
  // overrides that to 'plan_editing' so the recruiter can refine + re-publish.
  // Intentionally NOT cleared by setSessionId so it survives the navigation
  // that mounts the session route.
  editPlanSessionId: string | null;
  setEditPlanSession: (id: string | null) => void;

  // Voice connection error state (Phase 2)
  voiceError: {
    kind: 'mic_denied' | 'unreachable' | 'modality_conflict' | 'pc_failed';
    message: string;
  } | null;
  setVoiceError: (err: IntakeStoreState['voiceError']) => void;
  clearVoiceError: () => void;

  // hasLiveWebRTC — true while a PeerConnection is in 'connected' state.
  hasLiveWebRTC: boolean;
  setHasLiveWebRTC: (live: boolean) => void;

  // Phase 4: modality-switch state. pendingModality is written optimistically
  // by use-modality-switch.ts before the POST /switch resolves; the canvas
  // useEffect that watches session.active_modality clears it on row update.
  // switchError captures typed failure shapes (409 conflict, 502 drain failed,
  // generic) so the UI can render structured recovery affordances.
  pendingModality: PendingModality | null;
  switchError: SwitchError | null;

  // Phase 4 D1: process-till-now state. processTillNowRunId is the run id
  // returned from POST /reprocess; the hook watches session.process_status
  // and, on running → idle while a run id is held, snapshots current_answers
  // into diffBaseAnswers and flips diffPanelOpen open. The base snapshot
  // freezes the pre-reprocess answers so the diff view doesn't shift mid
  // review. reprocessError captures typed failure shapes for the UI.
  processTillNowRunId: string | null;
  diffPanelOpen: boolean;
  diffBaseAnswers: CurrentAnswers | null;
  reprocessError: ReprocessError | null;

  submittingError: string | null;
  setSubmittingError: (msg: string | null) => void;

  // Single source of truth for "a submit is in flight for this session id".
  // ALL submit paths (auto-submit on the canvas, the Wrapping-stage button, the
  // useSubmitIntake hook) gate on this so two paths can't double-fire one submit.
  // beginSubmit returns false when a submit is already in flight for the id.
  submitInFlightFor: string | null;
  beginSubmit: (sessionId: string) => boolean;
  endSubmit: (sessionId: string) => void;

  setSessionId: (id: string | null) => void;
  setPendingTransition: (to: IntakeStage, ttlMs: number) => void;
  clearPendingTransition: () => void;
  setError: (msg: string | null) => void;
  clearError: () => void;
  reset: () => void;
}

// Phase 1 keeps this store small on purpose: only the few client-only signals
// that aren't derivable from the IntakeSession row. Phases 2-4 will add
// pendingModality, processTillNowRunId, voice-connection error state, etc.
//
// pendingTransition powers the optimistic stage flip described in spec §4.3:
// derive-stage prefers pendingTransition over the row-derived stage until
// expiresAt elapses. The transition is auto-cleared on session change via
// the canvas useEffect that watches session.id + session.updated_at.
export const useIntakeStore = create<IntakeStoreState>((set, get) => ({
  sessionId: null,
  pendingTransition: null,
  error: null,

  endedSessionId: null,
  setEndedSession: (id) => set({ endedSessionId: id }),

  editPlanSessionId: null,
  setEditPlanSession: (id) => set({ editPlanSessionId: id }),

  voiceError: null,
  setVoiceError: (err) => set({ voiceError: err }),
  clearVoiceError: () => set({ voiceError: null }),
  hasLiveWebRTC: false,
  setHasLiveWebRTC: (live) => set({ hasLiveWebRTC: live }),

  pendingModality: null,
  switchError: null,

  processTillNowRunId: null,
  diffPanelOpen: false,
  diffBaseAnswers: null,
  reprocessError: null,

  submittingError: null,
  setSubmittingError: (msg) => set({ submittingError: msg }),

  submitInFlightFor: null,
  beginSubmit: (sessionId) => {
    if (get().submitInFlightFor === sessionId) return false;
    set({ submitInFlightFor: sessionId });
    return true;
  },
  endSubmit: (sessionId) => {
    if (get().submitInFlightFor === sessionId) set({ submitInFlightFor: null });
  },

  setSessionId: (id) =>
    set({
      sessionId: id,
      pendingTransition: null,
      error: null,
      endedSessionId: null,
      voiceError: null,
      hasLiveWebRTC: false,
      pendingModality: null,
      switchError: null,
      processTillNowRunId: null,
      diffPanelOpen: false,
      diffBaseAnswers: null,
      reprocessError: null,
      submittingError: null,
      submitInFlightFor: null,
    }),

  setPendingTransition: (to, ttlMs) =>
    set({ pendingTransition: { to, expiresAt: Date.now() + ttlMs } }),

  clearPendingTransition: () => set({ pendingTransition: null }),

  setError: (msg) => set({ error: msg }),
  clearError: () => set({ error: null }),

  reset: () =>
    set({
      sessionId: null,
      pendingTransition: null,
      error: null,
      endedSessionId: null,
      voiceError: null,
      hasLiveWebRTC: false,
      pendingModality: null,
      switchError: null,
      processTillNowRunId: null,
      diffPanelOpen: false,
      diffBaseAnswers: null,
      reprocessError: null,
      submittingError: null,
      submitInFlightFor: null,
      editPlanSessionId: null,
    }),
}));
