'use client';

// Single-page inline interview-plan editor (design: plan.jsx). Left rail =
// requisition + plan overview + edit/save toggle. Main = round cards with inline
// editing (name, duration, description, skills, guidelines, feedback questions)
// and drag-reorder. Footer = Back + Publish. Built on useInterviewPlanEditor.

import { Check, GripVertical, MoveRight, Pencil, Plus, Trash2 } from 'lucide-react';
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { useInterviewPlanEditor } from '@/hooks/intake/use-interview-plan-editor';
import { isRoundScreenable } from '@/lib/screening-eligibility';
import { roundScreeningToWire } from '@/services/screening';
import type {
  FeedbackQuestion,
  Guideline,
  IntakeSession,
  InterviewPlan,
  InterviewPlanRound,
  RoundScreening,
} from '@/types/intake';
import { IntakeScreeningPanel } from './intake-screening-panel';

// The backend "editable artifact" (intake-agent-v2) emits rounds keyed as
// `round_id`/`order_index` and feedback_questions with no id. The editor keys
// every React list key AND every update/remove off `id`/`round_number`, so an
// un-normalized plan renders with undefined keys and silently no-ops edits.
// Seed the editor with a normalized plan: prefer the real round_id, synthesize
// deterministic ids where the backend omits them. Ids must be deterministic
// (index-based) so re-normalizing the same plan is stable and never remounts a
// row mid-edit. Publish rebuilds rounds by name/category, so synthetic ids are
// never persisted.
function normalizePlan(plan: InterviewPlan): InterviewPlan {
  return {
    rounds: (plan.rounds ?? []).map((r, i) => {
      const raw = r as InterviewPlanRound & { round_id?: string; order_index?: number };
      const id = r.id ?? raw.round_id ?? `round-${i}`;
      const round_number =
        r.round_number ?? (raw.order_index != null ? raw.order_index + 1 : i + 1);
      return {
        ...r,
        id,
        round_number,
        skills: r.skills ?? [],
        guidelines: r.guidelines ?? [],
        feedback_questions: (r.feedback_questions ?? []).map((q, j) => ({
          ...q,
          id: q.id ?? `${id}-fq-${j}`,
          question_number: q.question_number ?? j + 1,
        })),
      };
    }),
  };
}

// Serialize the editor plan for publish. The editor holds `round.screening` in
// camelCase (reuses the screening service types/components); publish materializes
// the snake_case wire shape (intake_publish_service._materialize_screening), so
// map ONLY that field to wire here. Every other round field already matches the
// publish contract and is passed through untouched. Rounds without screening are
// returned as-is (no `screening` key).
function planForPublish(plan: InterviewPlan): InterviewPlan {
  return {
    rounds: plan.rounds.map((r) => {
      if (!r.screening) return r;
      const { screening, ...rest } = r;
      return {
        ...rest,
        // Cast: the wire shape is snake_case (what publish reads), not the
        // camelCase RoundScreening type. The payload is JSON-serialized, so the
        // runtime keys are what matter.
        screening: roundScreeningToWire(screening) as unknown as RoundScreening,
      };
    }),
  };
}

function fmtDur(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return ((h ? `${h}h` : '') + (m ? ` ${m}m` : '')).trim() || '0m';
}

const CATEGORY: Record<string, { label: string; tone: string }> = {
  screen: { label: 'Screen', tone: 'neutral' },
  screening: { label: 'Screen', tone: 'neutral' },
  coding: { label: 'Coding', tone: 'info' },
  design: { label: 'System Design', tone: 'cortex' },
  behavioral: { label: 'Behavioral', tone: 'warn' },
  culture: { label: 'Culture', tone: 'warn' },
  domain: { label: 'Domain', tone: 'cortex' },
  panel: { label: 'Panel', tone: 'neutral' },
  assessment: { label: 'Assessment', tone: 'neutral' },
};

// ── inline editable text ──
function EditableText({
  id,
  value,
  onCommit,
  multiline,
  placeholder,
  className,
  big,
  readOnly,
}: {
  id: string;
  value: string;
  onCommit: (v: string) => void;
  multiline?: boolean;
  placeholder?: string;
  className?: string;
  big?: boolean;
  readOnly?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!editing) return;
    const el = multiline ? areaRef.current : inputRef.current;
    el?.focus();
    el?.select?.();
  }, [editing, multiline]);

  if (readOnly) {
    return (
      <span id={id} className={`mz-ro${className ? ` ${className}` : ''}`}>
        {value || <span className="mz-edit-ph">{placeholder}</span>}
      </span>
    );
  }

  const commit = () => {
    setEditing(false);
    if (draft !== value) onCommit(draft);
  };

  if (editing) {
    const cls = `mz-edit-input${multiline ? ' mz-edit-area' : ''}${big ? ' mz-edit-big' : ''}`;
    return multiline ? (
      <textarea
        id={id}
        ref={areaRef}
        className={cls}
        value={draft}
        rows={2}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setDraft(value);
            setEditing(false);
          }
        }}
      />
    ) : (
      <input
        id={id}
        ref={inputRef}
        className={cls}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit();
          }
          if (e.key === 'Escape') {
            setDraft(value);
            setEditing(false);
          }
        }}
      />
    );
  }

  return (
    // biome-ignore lint/a11y/useSemanticElements: inline click-to-edit affordance; a <button> would break inline text flow
    <span
      id={id}
      className={`mz-editable${className ? ` ${className}` : ''}`}
      tabIndex={0}
      role="button"
      onClick={() => {
        setDraft(value);
        setEditing(true);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          setDraft(value);
          setEditing(true);
        }
      }}
    >
      {value || <span className="mz-edit-ph">{placeholder}</span>}
      <Pencil size={11} color="currentColor" />
    </span>
  );
}

// ── skills chips ──
function SkillChips({
  id,
  items,
  onChange,
  readOnly,
}: {
  id: string;
  items: string[];
  onChange: (next: string[]) => void;
  readOnly?: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const [val, setVal] = useState('');
  const add = () => {
    const v = val.trim();
    if (v) onChange([...items, v]);
    setVal('');
    setAdding(false);
  };
  return (
    <div id={id} className="mz-chips">
      {items.map((c) => (
        <span key={c} className="mz-chip">
          {c}
          {!readOnly && (
            <button
              type="button"
              onClick={() => onChange(items.filter((x) => x !== c))}
              aria-label={`Remove ${c}`}
            >
              <Trash2 size={10} color="currentColor" />
            </button>
          )}
        </span>
      ))}
      {!readOnly &&
        (adding ? (
          <input
            className="mz-chip-input"
            value={val}
            placeholder="Skill…"
            onChange={(e) => setVal(e.target.value)}
            onBlur={add}
            onKeyDown={(e) => {
              if (e.key === 'Enter') add();
              if (e.key === 'Escape') {
                setVal('');
                setAdding(false);
              }
            }}
          />
        ) : (
          <button type="button" className="mz-chip-add" onClick={() => setAdding(true)}>
            <Plus size={11} color="currentColor" /> Skill
          </button>
        ))}
    </div>
  );
}

// Per-round handler bundle — the editor methods pre-bound to THIS round's id.
// RoundCard takes this instead of the whole `editor` (which is a fresh object
// every render, so it would defeat React.memo). Built stable per round id in the
// parent so an unedited card's props stay referentially equal across renders.
interface RoundHandlers {
  updateRound: (patch: Partial<InterviewPlanRound>) => void;
  removeRound: () => void;
  addGuideline: (g: Guideline) => void;
  updateGuideline: (index: number, patch: Partial<Guideline>) => void;
  removeGuideline: (index: number) => void;
  addFeedbackQuestion: (q: Omit<FeedbackQuestion, 'id' | 'question_number'>) => void;
  updateFeedbackQuestion: (questionId: string, patch: Partial<FeedbackQuestion>) => void;
  removeFeedbackQuestion: (questionId: string) => void;
}

interface RoundCardProps {
  index: number;
  round: InterviewPlanRound;
  readOnly: boolean;
  handlers: RoundHandlers;
  dragId: string | null;
  grabRef: React.MutableRefObject<string | null>;
  onDragStart: (id: string) => void;
  onDragOver: (id: string) => void;
  onDragEnd: () => void;
  // Open the draft screening config panel for THIS round (pre-bound by the
  // parent, stable per round id so React.memo still skips unedited siblings).
  onConfigureScreening: () => void;
}

// memo comparator: skip re-render unless something THIS card actually renders
// from changed. Editing a sibling round leaves this round's object reference + its
// stable handler bundle untouched, so this returns true and the card is skipped.
// (Exported for unit testing the perf invariant.)
export function roundCardPropsEqual(prev: RoundCardProps, next: RoundCardProps): boolean {
  return (
    prev.round === next.round &&
    prev.handlers === next.handlers &&
    prev.readOnly === next.readOnly &&
    prev.index === next.index &&
    prev.dragId === next.dragId &&
    prev.grabRef === next.grabRef &&
    prev.onDragStart === next.onDragStart &&
    prev.onDragOver === next.onDragOver &&
    prev.onDragEnd === next.onDragEnd &&
    prev.onConfigureScreening === next.onConfigureScreening
  );
}

function RoundCardImpl({
  index,
  round,
  readOnly,
  handlers,
  dragId,
  grabRef,
  onDragStart,
  onDragOver,
  onDragEnd,
  onConfigureScreening,
}: RoundCardProps) {
  const cat = CATEGORY[round.category] ?? { label: round.category, tone: 'neutral' };
  const rid = round.id;

  // Screening affordances: a configured-and-enabled round shows the "OPENRECRUITING TAKES
  // THIS ROUND · NQ" badge; an eligible-but-unconfigured round shows the nudge +
  // "Set up screening". Eligibility mirrors the backend (lib/screening-eligibility).
  const screeningEnabled = round.screening?.enabled === true;
  const screeningQuestionCount = round.screening?.questions.length ?? 0;
  const screenable = isRoundScreenable(round.name, round.category, index);
  const showNudge = !readOnly && screenable && !screeningEnabled;

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: drag-reorder via the grip handle; reordering is also available by editing round order
    <div
      id={`intake-round-${rid}`}
      className="mz-round"
      data-dragging={dragId === rid ? 'true' : undefined}
      draggable={!readOnly && grabRef.current === rid}
      onDragStart={() => onDragStart(rid)}
      onDragEnd={onDragEnd}
      onDragOver={(e) => {
        e.preventDefault();
        onDragOver(rid);
      }}
    >
      <div className="mz-round-spine">
        {!readOnly && (
          <button
            type="button"
            className="mz-round-grip"
            onMouseDown={() => {
              grabRef.current = rid;
            }}
            onMouseUp={() => {
              grabRef.current = null;
            }}
            aria-label="Drag to reorder"
          >
            <GripVertical size={15} />
          </button>
        )}
        <span className="mz-round-num">{index + 1}</span>
        <span className="mz-round-line" />
      </div>

      <div className="mz-round-card">
        <div className="mz-round-top">
          <div className="mz-round-head">
            <div className="mz-round-badges">
              <span className={`mz-cat mz-cat-${cat.tone}`}>{cat.label}</span>
              {screeningEnabled && (
                <button
                  id={`intake-round-${rid}-screening-badge`}
                  type="button"
                  className="mz-screening-badge"
                  onClick={onConfigureScreening}
                  disabled={readOnly}
                >
                  <BrandIcon className="mz-screening-icon" />
                  OpenRecruiting takes this round
                  {screeningQuestionCount > 0 ? ` · ${screeningQuestionCount}Q` : ''}
                </button>
              )}
              {showNudge && (
                <button
                  id={`intake-round-${rid}-screening-nudge`}
                  type="button"
                  className="mz-screening-nudge"
                  onClick={onConfigureScreening}
                >
                  <BrandIcon className="mz-screening-icon" />
                  OpenRecruiting can take this round · Set up screening
                </button>
              )}
            </div>
            <EditableText
              id={`intake-round-${rid}-name`}
              value={round.name}
              onCommit={(v) => handlers.updateRound({ name: v })}
              className="mz-round-name"
              big
              readOnly={readOnly}
              placeholder="Round name"
            />
            <div className="mz-round-meta">
              <span className="mz-round-pill">
                <EditableText
                  id={`intake-round-${rid}-dur`}
                  value={String(round.duration_minutes)}
                  onCommit={(v) => handlers.updateRound({ duration_minutes: parseInt(v, 10) || 0 })}
                  className="mz-round-dur"
                  readOnly={readOnly}
                  placeholder="30"
                />{' '}
                min
              </span>
            </div>
          </div>
          {!readOnly && (
            <button
              type="button"
              className="mz-round-del"
              onClick={() => handlers.removeRound()}
              aria-label="Delete round"
            >
              <Trash2 size={16} />
            </button>
          )}
        </div>

        <EditableText
          id={`intake-round-${rid}-desc`}
          value={round.description}
          onCommit={(v) => handlers.updateRound({ description: v })}
          multiline
          className="mz-round-desc"
          readOnly={readOnly}
          placeholder="Describe the purpose of this round…"
        />

        <div className="mz-round-section">
          <div className="mz-round-label">Skills tested</div>
          <SkillChips
            id={`intake-round-${rid}-skills`}
            items={round.skills}
            onChange={(v) => handlers.updateRound({ skills: v })}
            readOnly={readOnly}
          />
        </div>

        <div className="mz-round-section">
          <div className="mz-round-label">Interviewer guidelines</div>
          <div className="mz-guides">
            {round.guidelines.map((g, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: guidelines have no stable id; the index is the canonical handle used by update/remove
              <div key={`g-${i}`} className="mz-guide">
                <span className="mz-guide-mark" />
                <div className="mz-guide-body">
                  <EditableText
                    id={`intake-round-${rid}-guide-${i}-title`}
                    value={g.title}
                    onCommit={(v) => handlers.updateGuideline(i, { title: v })}
                    className="mz-guide-title"
                    readOnly={readOnly}
                    placeholder="Guideline title"
                  />
                  <EditableText
                    id={`intake-round-${rid}-guide-${i}-desc`}
                    value={g.description}
                    onCommit={(v) => handlers.updateGuideline(i, { description: v })}
                    multiline
                    className="mz-guide-desc"
                    readOnly={readOnly}
                    placeholder="Add guidance…"
                  />
                </div>
                {!readOnly && (
                  <button
                    type="button"
                    className="mz-row-del"
                    onClick={() => handlers.removeGuideline(i)}
                    aria-label="Delete guideline"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            ))}
            {!readOnly && (
              <button
                type="button"
                className="mz-mini-add"
                onClick={() =>
                  handlers.addGuideline({ title: 'New guideline', description: '' } as Guideline)
                }
              >
                <Plus size={13} color="currentColor" /> Add guideline
              </button>
            )}
          </div>
        </div>

        <div className="mz-round-section">
          <div className="mz-round-label">Feedback questions</div>
          <div className="mz-rubric">
            {round.feedback_questions.map((q, i) => (
              <div key={q.id} className="mz-crit">
                <span className="mz-crit-num">{i + 1}</span>
                <div className="mz-crit-body">
                  <EditableText
                    id={`intake-round-${rid}-fq-${q.id}-heading`}
                    value={q.heading}
                    onCommit={(v) => handlers.updateFeedbackQuestion(q.id, { heading: v })}
                    className="mz-crit-h"
                    readOnly={readOnly}
                    placeholder="Criterion"
                  />
                  <EditableText
                    id={`intake-round-${rid}-fq-${q.id}-desc`}
                    value={q.description ?? ''}
                    onCommit={(v) => handlers.updateFeedbackQuestion(q.id, { description: v })}
                    multiline
                    className="mz-crit-d"
                    readOnly={readOnly}
                    placeholder="Evaluation guidance (optional)"
                  />
                </div>
                {!readOnly && (
                  <button
                    type="button"
                    className="mz-row-del"
                    onClick={() => handlers.removeFeedbackQuestion(q.id)}
                    aria-label="Delete feedback question"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            ))}
            {!readOnly && (
              <button
                type="button"
                className="mz-mini-add"
                onClick={() =>
                  handlers.addFeedbackQuestion({ heading: 'New criterion', description: '' })
                }
              >
                <Plus size={13} color="currentColor" /> Add question
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// Memoized so editing one round never re-renders its siblings (each unedited
// round keeps the same `round` ref + the same stable handler bundle).
const RoundCard = memo(RoundCardImpl, roundCardPropsEqual);

interface Props {
  id: string;
  session: IntakeSession;
  initialPlan: InterviewPlan;
  isPublishing: boolean;
  publishError: string | null;
  onPublish: (plan: InterviewPlan) => void;
  onBack: () => void;
}

export function InterviewPlanEditor({
  id,
  session,
  initialPlan,
  isPublishing,
  publishError,
  onPublish,
  onBack,
}: Props) {
  const normalizedPlan = useMemo(() => normalizePlan(initialPlan), [initialPlan]);
  const editor = useInterviewPlanEditor(normalizedPlan);
  const [editMode, setEditMode] = useState(true);
  // Which round's draft screening panel is open (by round id), or null.
  const [screeningRoundId, setScreeningRoundId] = useState<string | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const grabRef = useRef<string | null>(null);
  // dragId mirror so reorderTo can stay a stable useCallback (a fresh closure
  // each render would re-render every memoized RoundCard).
  const dragIdRef = useRef<string | null>(null);
  dragIdRef.current = dragId;

  // Stable per-round handler bundles, cached by round id. The editor methods are
  // all stable useCallbacks, so a bundle is built once per round and stays
  // referentially equal — this is what lets React.memo skip unedited sibling
  // cards (the whole `editor` object is fresh every render and would defeat it).
  const handlersRef = useRef<Map<string, RoundHandlers>>(new Map());
  const getRoundHandlers = useCallback(
    (rid: string): RoundHandlers => {
      const cached = handlersRef.current.get(rid);
      if (cached) return cached;
      const bundle: RoundHandlers = {
        updateRound: (patch) => editor.updateRound(rid, patch),
        removeRound: () => editor.removeRound(rid),
        addGuideline: (g) => editor.addGuideline(rid, g),
        updateGuideline: (index, patch) => editor.updateGuideline(rid, index, patch),
        removeGuideline: (index) => editor.removeGuideline(rid, index),
        addFeedbackQuestion: (q) => editor.addFeedbackQuestion(rid, q),
        updateFeedbackQuestion: (questionId, patch) =>
          editor.updateFeedbackQuestion(rid, questionId, patch),
        removeFeedbackQuestion: (questionId) => editor.removeFeedbackQuestion(rid, questionId),
      };
      handlersRef.current.set(rid, bundle);
      return bundle;
    },
    [editor],
  );

  // Stable per-round "open screening panel" callbacks, cached by round id so the
  // memoized RoundCard isn't re-rendered by a fresh closure each render (same
  // reasoning as the handler bundles above). setScreeningRoundId is a stable
  // setState dispatcher, so each callback is built once and stays equal.
  const openScreeningRef = useRef<Map<string, () => void>>(new Map());
  const getOpenScreening = useCallback((rid: string): (() => void) => {
    const cached = openScreeningRef.current.get(rid);
    if (cached) return cached;
    const open = () => setScreeningRoundId(rid);
    openScreeningRef.current.set(rid, open);
    return open;
  }, []);

  // Reset the editor if the backing plan identity changes (e.g. a fresh plan
  // landed via realtime). Keyed by round ids so in-place edits don't reset.
  const planKey = normalizedPlan.rounds.map((r) => r.id).join('|');
  const lastKeyRef = useRef(planKey);
  useEffect(() => {
    if (lastKeyRef.current !== planKey) {
      lastKeyRef.current = planKey;
      editor.reset(normalizedPlan);
    }
  }, [planKey, normalizedPlan, editor]);

  // Undo (Ctrl/Cmd+Z) when focus isn't in an input.
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      const t = e.target as HTMLElement | null;
      const inField =
        t?.tagName === 'INPUT' || t?.tagName === 'TEXTAREA' || t?.isContentEditable === true;
      if (inField) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (editor.canUndo) editor.undo();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [editor]);

  const { role_name, experience_min, experience_max, location } = session.form_data;
  const totalMin = editor.plan.rounds.reduce((s, r) => s + (r.duration_minutes || 0), 0);
  // Resolve the open screening panel's round from the LIVE plan so the panel
  // always reflects the latest screening object (e.g. after generate/derive).
  const screeningRound = screeningRoundId
    ? (editor.plan.rounds.find((r) => r.id === screeningRoundId) ?? null)
    : null;

  const reorderTo = useCallback(
    (targetId: string) => {
      const dragging = dragIdRef.current;
      if (!dragging || dragging === targetId) return;
      const from = editor.plan.rounds.findIndex((r) => r.id === dragging);
      const to = editor.plan.rounds.findIndex((r) => r.id === targetId);
      if (from < 0 || to < 0) return;
      editor.reorderRounds(from, to);
    },
    [editor],
  );

  const onDragEnd = useCallback(() => {
    setDragId(null);
    grabRef.current = null;
  }, []);

  return (
    <div id={id} className="mz-plan">
      <div className="mz-plan-body">
        <aside id={`${id}-rail`} className="mz-plan-rail">
          <div className="mz-eyebrow">Requisition</div>
          <div className="mz-rail-role">{role_name}</div>
          <div className="mz-rail-sub">
            {experience_min}–{experience_max} yrs · {location}
          </div>

          <div className="mz-rail-div" />
          <div className="mz-eyebrow">Plan overview</div>
          <div className="mz-rail-stats">
            <div>
              <span className="mz-stat-n">{editor.plan.rounds.length}</span>
              <span className="mz-stat-l">Rounds</span>
            </div>
            <div>
              <span className="mz-stat-n">{fmtDur(totalMin)}</span>
              <span className="mz-stat-l">Total time</span>
            </div>
          </div>

          <div className="mz-rail-div" />
          <div className="mz-rail-actions">
            {/* Pure view/edit toggle — NOT a save. The plan is only persisted on
                Publish (there is no draft-persist endpoint), so this must never
                claim a save that didn't happen. */}
            <button
              id={`${id}-edit-toggle`}
              type="button"
              className="mz-rail-btn"
              onClick={() => setEditMode((e) => !e)}
            >
              {editMode ? <Check size={15} /> : <Pencil size={15} />}
              {editMode ? 'Done editing' : 'Edit plan'}
            </button>
          </div>
          <div className="mz-rail-hint">Changes save when you publish.</div>
        </aside>

        <div className="mz-plan-main">
          <div className="mz-plan-inner">
            <div className="mz-plan-banner">
              <Check size={14} color="var(--status-success-fg)" strokeWidth={3} />
              Intake captured — OpenRecruiting drafted this plan from your goals.{' '}
              {editMode ? 'Everything below is editable.' : 'Select Edit plan to make changes.'}
            </div>
            <div className="mz-rounds">
              {editor.plan.rounds.map((r, i) => (
                <RoundCard
                  key={r.id}
                  index={i}
                  round={r}
                  readOnly={!editMode}
                  handlers={getRoundHandlers(r.id)}
                  dragId={dragId}
                  grabRef={grabRef}
                  onDragStart={setDragId}
                  onDragOver={reorderTo}
                  onDragEnd={onDragEnd}
                  onConfigureScreening={getOpenScreening(r.id)}
                />
              ))}
            </div>
          </div>
        </div>
      </div>

      {screeningRound && (
        <IntakeScreeningPanel
          id={`${id}-screening-panel`}
          sessionId={session.id}
          round={screeningRound}
          screening={screeningRound.screening}
          onChange={(next) => editor.setRoundScreening(screeningRound.id, next)}
          onClose={() => setScreeningRoundId(null)}
        />
      )}

      <div className="mz-plan-foot">
        <button id={`${id}-back`} type="button" className="mz-btn-ghost" onClick={onBack}>
          Back
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {publishError ? (
            <span id={`${id}-error`} role="alert" className="text-sm text-[var(--danger-fg)]">
              {publishError}
            </span>
          ) : (
            <span className="mz-plan-saved">Not saved until you publish</span>
          )}
          <button
            id={`${id}-publish`}
            type="button"
            className="mz-btn-dark"
            disabled={isPublishing || !editor.canPublish}
            onClick={() => onPublish(planForPublish(editor.plan))}
          >
            {isPublishing ? 'Publishing…' : 'Publish to requisition'}
            <MoveRight size={16} color="currentColor" />
          </button>
        </div>
      </div>
    </div>
  );
}
