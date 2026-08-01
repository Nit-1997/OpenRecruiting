import { create } from 'zustand';
import * as screening from '@/services/screening';
import type {
  FeedbackQuestion,
  Guideline,
  IntakeEvent,
  IntakeScreeningQuestion,
  Requisition,
  RoundCategory,
} from '@/types';

function clone<T>(x: T): T {
  return structuredClone(x);
}

function nowIso(): string {
  return new Date().toISOString();
}

function genId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
}

const DEFAULT_SCREENING_VOICE = 'Aura · "Luna"';

// Map a service screening question (camelCase, server shape) to the store/UI
// IntakeScreeningQuestion. The two diverge: the service uses title/prompt +
// orderIndex; the UI uses question + order and always needs a stable id.
function intakeQuestionFromService(q: screening.ScreeningQuestion): IntakeScreeningQuestion {
  return {
    id: q.id ?? genId('sq'),
    order: q.orderIndex,
    dimension: q.dimension,
    question: q.title || q.prompt,
    probe: q.probe,
    durationMinutes: q.durationMinutes,
    signal: q.signal,
  };
}

function serviceQuestionFromIntake(q: IntakeScreeningQuestion): screening.ScreeningQuestion {
  return {
    id: q.id,
    orderIndex: q.order,
    title: q.question,
    prompt: q.question,
    probe: q.probe,
    signal: q.signal,
    dimension: q.dimension,
    durationMinutes: q.durationMinutes,
  };
}

// Build a full ScreeningConfig from store-side question state. Used to persist
// the recruiter's edits via PUT before flipping enabled on attach.
function configFromIntake(
  roundId: string,
  questions: IntakeScreeningQuestion[],
  voice: string,
  enabled: boolean,
): screening.ScreeningConfig {
  return {
    roundId,
    enabled,
    voice,
    followUpStyle: 'adaptive',
    estDurationMinutes: questions.reduce((sum, q) => sum + (q.durationMinutes || 0), 0),
    validityDays: 14,
    deployScope: 'all_resume_passed',
    questions: questions.map(serviceQuestionFromIntake),
  };
}

export interface CreateRoundInput {
  name: string;
  category: RoundCategory;
  durationMinutes?: number;
  description?: string;
  skills?: string[];
}

export interface UpdateRoundPatch {
  name?: string;
  category?: RoundCategory;
  durationMinutes?: number;
  description?: string;
  skills?: string[];
}

export interface UpdateQuestionPatch {
  heading?: string;
  description?: string | null;
}

export type ValidatePublishResult =
  | { ok: true }
  | { ok: false; errors: Array<{ roundId: string; reason: 'no_name' | 'no_questions' }> };

interface UndoEntry {
  reqId: string;
  before: Requisition;
}

interface RequisitionStoreState {
  requisitions: Record<string, Requisition>;
  undoStack: UndoEntry[];

  upsertRequisition: (req: Requisition) => void;
  removeRequisition: (id: string) => void;
  applyEvent: (reqId: string, event: IntakeEvent) => void;

  addRound: (reqId: string, input: CreateRoundInput) => void;
  reorderRounds: (reqId: string, orderedIds: string[]) => void;
  updateRound: (roundId: string, patch: UpdateRoundPatch) => void;
  deleteRound: (roundId: string) => void;

  addQuestion: (roundId: string, input: { heading: string; description?: string | null }) => void;
  updateQuestion: (questionId: string, patch: UpdateQuestionPatch) => void;
  deleteQuestion: (questionId: string) => void;

  updateGuidelines: (roundId: string, guidelines: Guideline[]) => void;
  updateHeader: (
    reqId: string,
    patch: {
      roleTitle?: string;
      roleLocation?: string;
      experienceMinYears?: number;
      experienceMaxYears?: number | null;
    },
  ) => void;

  undo: () => void;
  validatePublish: (reqId: string) => ValidatePublishResult;
  publish: (reqId: string) => ValidatePublishResult;

  setDashboardRequisitionId: (reqId: string, dashboardId: string) => void;

  attachScreeningAgent: (
    roundId: string,
    questions: IntakeScreeningQuestion[],
    voice?: string,
  ) => Promise<void>;
  detachScreeningAgent: (roundId: string) => Promise<void>;
  updateScreeningQuestion: (
    roundId: string,
    questionId: string,
    patch: Partial<Omit<IntakeScreeningQuestion, 'id'>>,
  ) => Promise<void>;

  reset: () => void;
}

function findReqIdByRoundId(
  reqs: Record<string, Requisition>,
  roundId: string,
): string | undefined {
  for (const r of Object.values(reqs)) {
    if (r.rounds.some((rd) => rd.id === roundId)) return r.id;
  }
  return undefined;
}

function findReqIdByQuestionId(
  reqs: Record<string, Requisition>,
  questionId: string,
): string | undefined {
  for (const r of Object.values(reqs)) {
    if (r.rounds.some((rd) => rd.feedbackQuestions.some((q) => q.id === questionId))) return r.id;
  }
  return undefined;
}

function renumberRounds(req: Requisition): Requisition {
  return {
    ...req,
    rounds: req.rounds.map((r, i) => ({ ...r, roundNumber: i + 1 })),
  };
}

function renumberQuestions(req: Requisition): Requisition {
  return {
    ...req,
    rounds: req.rounds.map((r) => ({
      ...r,
      feedbackQuestions: r.feedbackQuestions.map((q, i) => ({ ...q, questionNumber: i + 1 })),
    })),
  };
}

export const useRequisitionStore = create<RequisitionStoreState>((set, get) => {
  function mutate(reqId: string, fn: (r: Requisition) => Requisition) {
    set((state) => {
      const existing = state.requisitions[reqId];
      if (!existing) return state;
      const snapshot = clone(existing);
      const next = { ...fn(existing), updatedAt: nowIso() };
      return {
        requisitions: { ...state.requisitions, [reqId]: next },
        undoStack: [...state.undoStack, { reqId, before: snapshot }],
      };
    });
  }

  function mutateNoUndo(reqId: string, fn: (r: Requisition) => Requisition) {
    set((state) => {
      const existing = state.requisitions[reqId];
      if (!existing) return state;
      const next = { ...fn(existing), updatedAt: nowIso() };
      return { requisitions: { ...state.requisitions, [reqId]: next } };
    });
  }

  // Reconcile a round with the server's saved config (the source of truth after
  // a save/attach/detach). Maps the service config back to the store's UI shape.
  function writeServerConfig(reqId: string, roundId: string, config: screening.ScreeningConfig) {
    mutateNoUndo(reqId, (r) => ({
      ...r,
      rounds: r.rounds.map((rd) =>
        rd.id === roundId
          ? {
              ...rd,
              screeningAgentEnabled: config.enabled,
              screeningAgentVoice: config.voice,
              screeningAgentQuestions: config.questions.map(intakeQuestionFromService),
            }
          : rd,
      ),
    }));
  }

  return {
    requisitions: {},
    undoStack: [],

    upsertRequisition: (req) =>
      set((state) => ({
        requisitions: { ...state.requisitions, [req.id]: clone(req) },
      })),

    removeRequisition: (id) =>
      set((state) => {
        const { [id]: _removed, ...rest } = state.requisitions;
        return { requisitions: rest };
      }),

    applyEvent: (reqId, event) => {
      mutateNoUndo(reqId, (r) => {
        switch (event.type) {
          case 'stage': {
            const status = event.stage === 'completed' ? 'completed' : 'processing';
            return { ...r, intakeProcessingStage: event.stage, intakeProcessingStatus: status };
          }
          case 'summary.delta':
            return { ...r, intakeSummary: (r.intakeSummary ?? '') + event.token };
          case 'round.created': {
            if (r.rounds.some((rd) => rd.id === event.round.id)) return r;
            return { ...r, rounds: [...r.rounds, clone(event.round)] };
          }
          case 'round.details': {
            return {
              ...r,
              rounds: r.rounds.map((rd) =>
                rd.id === event.roundId
                  ? {
                      ...rd,
                      guidelines: clone(event.guidelines),
                      feedbackQuestions: clone(event.feedbackQuestions),
                    }
                  : rd,
              ),
            };
          }
          case 'done':
            return {
              ...r,
              intakeProcessingStage: 'completed',
              intakeProcessingStatus: 'completed',
            };
          case 'error':
            return { ...r, intakeProcessingStatus: 'failed' };
          default:
            return r;
        }
      });
    },

    addRound: (reqId, input) => {
      mutate(reqId, (r) => {
        const next = clone(r);
        next.rounds.push({
          id: genId('rnd'),
          requisitionId: reqId,
          roundNumber: next.rounds.length + 1,
          name: input.name,
          category: input.category,
          durationMinutes: input.durationMinutes ?? 45,
          description: input.description ?? '',
          skills: input.skills ?? [],
          guidelines: [],
          feedbackQuestions: [],
        });
        return next;
      });
    },

    reorderRounds: (reqId, orderedIds) => {
      mutate(reqId, (r) => {
        const byId = new Map(r.rounds.map((rd) => [rd.id, rd]));
        const reordered = orderedIds
          .map((id) => byId.get(id))
          .filter((rd): rd is NonNullable<typeof rd> => rd !== undefined);
        return renumberRounds({ ...r, rounds: reordered });
      });
    },

    updateRound: (roundId, patch) => {
      const reqId = findReqIdByRoundId(get().requisitions, roundId);
      if (!reqId) return;
      mutate(reqId, (r) => ({
        ...r,
        rounds: r.rounds.map((rd) => (rd.id === roundId ? { ...rd, ...patch } : rd)),
      }));
    },

    deleteRound: (roundId) => {
      const reqId = findReqIdByRoundId(get().requisitions, roundId);
      if (!reqId) return;
      mutate(reqId, (r) =>
        renumberRounds({ ...r, rounds: r.rounds.filter((rd) => rd.id !== roundId) }),
      );
    },

    addQuestion: (roundId, input) => {
      const reqId = findReqIdByRoundId(get().requisitions, roundId);
      if (!reqId) return;
      mutate(reqId, (r) => ({
        ...r,
        rounds: r.rounds.map((rd) => {
          if (rd.id !== roundId) return rd;
          const q: FeedbackQuestion = {
            id: genId('fq'),
            roundId,
            questionNumber: rd.feedbackQuestions.length + 1,
            heading: input.heading,
            description: input.description ?? null,
          };
          return { ...rd, feedbackQuestions: [...rd.feedbackQuestions, q] };
        }),
      }));
    },

    updateQuestion: (questionId, patch) => {
      const reqId = findReqIdByQuestionId(get().requisitions, questionId);
      if (!reqId) return;
      mutate(reqId, (r) => ({
        ...r,
        rounds: r.rounds.map((rd) => ({
          ...rd,
          feedbackQuestions: rd.feedbackQuestions.map((q) =>
            q.id === questionId ? { ...q, ...patch } : q,
          ),
        })),
      }));
    },

    deleteQuestion: (questionId) => {
      const reqId = findReqIdByQuestionId(get().requisitions, questionId);
      if (!reqId) return;
      mutate(reqId, (r) =>
        renumberQuestions({
          ...r,
          rounds: r.rounds.map((rd) => ({
            ...rd,
            feedbackQuestions: rd.feedbackQuestions.filter((q) => q.id !== questionId),
          })),
        }),
      );
    },

    updateGuidelines: (roundId, guidelines) => {
      const reqId = findReqIdByRoundId(get().requisitions, roundId);
      if (!reqId) return;
      mutate(reqId, (r) => ({
        ...r,
        rounds: r.rounds.map((rd) =>
          rd.id === roundId ? { ...rd, guidelines: clone(guidelines) } : rd,
        ),
      }));
    },

    updateHeader: (reqId, patch) => {
      mutate(reqId, (r) => ({ ...r, ...patch }));
    },

    undo: () => {
      set((state) => {
        const entry = state.undoStack[state.undoStack.length - 1];
        if (!entry) return state;
        const nextStack = state.undoStack.slice(0, -1);
        return {
          requisitions: { ...state.requisitions, [entry.reqId]: entry.before },
          undoStack: nextStack,
        };
      });
    },

    validatePublish: (reqId) => {
      const r = get().requisitions[reqId];
      if (!r) return { ok: false, errors: [] };
      const errors: Array<{ roundId: string; reason: 'no_name' | 'no_questions' }> = [];
      for (const rd of r.rounds) {
        if (!rd.name.trim()) errors.push({ roundId: rd.id, reason: 'no_name' });
        else if (rd.feedbackQuestions.length === 0)
          errors.push({ roundId: rd.id, reason: 'no_questions' });
      }
      if (errors.length === 0) return { ok: true };
      return { ok: false, errors };
    },

    publish: (reqId) => {
      const check = get().validatePublish(reqId);
      if (!check.ok) return check;
      mutate(reqId, (r) => ({ ...r, status: 'planned' }));
      return { ok: true };
    },

    setDashboardRequisitionId: (reqId, dashboardId) =>
      mutate(reqId, (r) => ({ ...r, dashboardRequisitionId: dashboardId })),

    // Persist the screening config (PUT) then flip enabled (POST attach). We
    // update local state optimistically first so the UI reflects the attach
    // immediately, then reconcile against the server's response. On API failure
    // the local state stays — callers surface errors via the rethrow.
    attachScreeningAgent: async (roundId, questions, voice) => {
      const reqId = findReqIdByRoundId(get().requisitions, roundId);
      if (!reqId) return;
      const chosenVoice =
        voice ??
        get().requisitions[reqId]?.rounds.find((rd) => rd.id === roundId)?.screeningAgentVoice ??
        DEFAULT_SCREENING_VOICE;
      mutateNoUndo(reqId, (r) => ({
        ...r,
        rounds: r.rounds.map((rd) =>
          rd.id === roundId
            ? {
                ...rd,
                screeningAgentEnabled: true,
                screeningAgentVoice: chosenVoice,
                screeningAgentQuestions: clone(questions),
              }
            : rd,
        ),
      }));
      await screening.saveScreening(
        reqId,
        roundId,
        configFromIntake(roundId, questions, chosenVoice, true),
      );
      const saved = await screening.attachScreening(reqId, roundId);
      writeServerConfig(reqId, roundId, saved);
    },

    detachScreeningAgent: async (roundId) => {
      const reqId = findReqIdByRoundId(get().requisitions, roundId);
      if (!reqId) return;
      mutateNoUndo(reqId, (r) => ({
        ...r,
        rounds: r.rounds.map((rd) =>
          rd.id === roundId ? { ...rd, screeningAgentEnabled: false } : rd,
        ),
      }));
      const saved = await screening.detachScreening(reqId, roundId);
      writeServerConfig(reqId, roundId, saved);
    },

    updateScreeningQuestion: async (roundId, questionId, patch) => {
      const reqId = findReqIdByRoundId(get().requisitions, roundId);
      if (!reqId) return;
      mutateNoUndo(reqId, (r) => ({
        ...r,
        rounds: r.rounds.map((rd) => {
          if (rd.id !== roundId) return rd;
          const qs = rd.screeningAgentQuestions ?? [];
          return {
            ...rd,
            screeningAgentQuestions: qs.map((q) => (q.id === questionId ? { ...q, ...patch } : q)),
          };
        }),
      }));
      const round = get().requisitions[reqId]?.rounds.find((rd) => rd.id === roundId);
      if (!round) return;
      const voice = round.screeningAgentVoice ?? DEFAULT_SCREENING_VOICE;
      const saved = await screening.saveScreening(
        reqId,
        roundId,
        configFromIntake(
          roundId,
          round.screeningAgentQuestions ?? [],
          voice,
          round.screeningAgentEnabled === true,
        ),
      );
      writeServerConfig(reqId, roundId, saved);
    },

    reset: () => set({ requisitions: {}, undoStack: [] }),
  };
});
