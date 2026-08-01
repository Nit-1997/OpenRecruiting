'use client';

// hub.tsx — the intake landing. Three deterministic actions:
//   Start a new role · Continue pending · Edit existing
// Replaces the old chart-based chat lobby. Data comes from the enriched
// /intake/sessions list (covered/total/stopped_at for pending rows;
// rounds/total_minutes/candidates for published rows).

import {
  ArrowLeft,
  ArrowRight,
  ClipboardCheck,
  Clock,
  Mic,
  MoveRight,
  Pencil,
  Sparkles,
  X,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import { IntakeHubSkeleton } from '@/components/shell/skeletons';
import { Orb } from '@/components/sub-agents/intake/primitives';
import { ProgressRing } from '@/components/sub-agents/intake/primitives/progress-ring';
import { useIntakeSessionsList } from '@/hooks/intake/use-intake-sessions-list';
import { createIntakeSession, IntakeApiError } from '@/lib/intake/api';
import { useIntakeStore } from '@/stores/intake-store';
import type { SessionListItem } from '@/types/intake';
import { JobDescriptionField } from '../components/job-description-field';
import { LocationAutocomplete } from '../components/location-autocomplete';

function fmtDur(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return ((h ? `${h}h` : '') + (m ? ` ${m}m` : '')).trim() || '0m';
}

function fmtRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (secs < 60) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return `${Math.floor(days / 7)}w ago`;
}

function expLocation(s: SessionListItem): string {
  const parts: string[] = [];
  if (s.exp_min != null && s.exp_max != null) parts.push(`${s.exp_min}–${s.exp_max} yrs`);
  if (s.location) parts.push(s.location);
  return parts.join(' · ');
}

// ── New-role popup (collect role context) ──
function NewRoleModal({
  id,
  onClose,
  onStart,
}: {
  id: string;
  onClose: () => void;
  onStart: (f: {
    roleName: string;
    expMin: number;
    expMax: number | null;
    location: string;
    jd: string;
  }) => void;
}) {
  const [roleName, setRoleName] = useState('');
  const [expMin, setExpMin] = useState('7');
  const [expMax, setExpMax] = useState('11');
  const [location, setLocation] = useState('Remote · US');
  const [jd, setJd] = useState('');
  const [busy, setBusy] = useState(false);
  const [rangeError, setRangeError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!roleName.trim() || busy) return;
    const min = Number(expMin) || 0;
    // A blank max stays open-ended → null ("X+ years"). Never coerce to 0.
    const maxRaw = expMax.trim();
    const max = maxRaw === '' ? null : Number(maxRaw);
    if (max !== null && (Number.isNaN(max) || max < min)) {
      setRangeError('Max experience must be greater than or equal to min.');
      return;
    }
    setRangeError(null);
    setBusy(true);
    onStart({
      roleName: roleName.trim(),
      expMin: min,
      expMax: max,
      location: location.trim(),
      jd: jd.trim(),
    });
  };

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: backdrop is a progressive enhancement, not the primary control
    <div
      id={`${id}-scrim`}
      className="mz-modal-scrim"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose();
      }}
    >
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: onClick only stops backdrop dismissal when clicking inside the dialog; not an interactive control */}
      <div
        id={id}
        className="mz-modal mz-modal-form"
        role="dialog"
        aria-modal="true"
        aria-label="Tell OpenRecruiting about the role"
        onClick={(e) => e.stopPropagation()}
      >
        <div id={`${id}-head`} className="mz-modal-formhead">
          <div id={`${id}-icon`} className="mz-modal-formicon">
            <Sparkles size={18} color="var(--cortex-600)" />
          </div>
          <div className="mz-modal-formheadtext">
            <div className="mz-eyebrow">New role</div>
            <h3 id={`${id}-title`} className="mz-modal-title">
              Tell OpenRecruiting about the role
            </h3>
          </div>
          <button
            id={`${id}-close`}
            type="button"
            className="mz-modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
        <form id={`${id}-form`} onSubmit={submit} className="mz-modal-body">
          <div className="mz-field">
            <label htmlFor={`${id}-role`}>Role name</label>
            <input
              id={`${id}-role`}
              value={roleName}
              onChange={(e) => setRoleName(e.target.value)}
              placeholder="Senior Backend Engineer"
            />
          </div>
          <div className="mz-field-row">
            <div className="mz-field">
              <label htmlFor={`${id}-expmin`}>Min experience</label>
              <div className="mz-suffix">
                <input
                  id={`${id}-expmin`}
                  type="number"
                  min={0}
                  max={40}
                  value={expMin}
                  onChange={(e) => setExpMin(e.target.value)}
                />
                <span>yrs</span>
              </div>
            </div>
            <div className="mz-field">
              <label htmlFor={`${id}-expmax`}>
                Max experience <span className="mz-opt">optional</span>
              </label>
              <div className="mz-suffix">
                <input
                  id={`${id}-expmax`}
                  type="number"
                  min={0}
                  max={40}
                  value={expMax}
                  onChange={(e) => setExpMax(e.target.value)}
                  placeholder="No max"
                />
                <span>yrs</span>
              </div>
            </div>
          </div>
          <div className="mz-field">
            {/* biome-ignore lint/a11y/noLabelWithoutControl: label points at the autocomplete's inner input via its own htmlFor */}
            <label>Location</label>
            <LocationAutocomplete
              id={`${id}-location`}
              value={location}
              onChange={setLocation}
              placeholder="Remote · Bengaluru · SF"
            />
          </div>
          <div className="mz-field">
            {/* biome-ignore lint/a11y/noLabelWithoutControl: JD field is a composite control with its own inputs */}
            <label>
              Job description <span className="mz-opt">optional</span>
            </label>
            <JobDescriptionField id={`${id}-jd`} onChange={setJd} />
          </div>
          {rangeError && (
            <div
              id={`${id}-range-error`}
              role="alert"
              className="px-5 text-sm text-[var(--danger-fg)]"
            >
              {rangeError}
            </div>
          )}
          <div className="mz-modal-foot">
            <span className="mz-form-note">OpenRecruiting gathers context, then opens the call.</span>
            <button
              id={`${id}-submit`}
              type="submit"
              className="mz-btn-dark"
              disabled={busy || !roleName.trim()}
            >
              {busy ? 'Starting…' : 'Start intake'}
              <MoveRight size={16} color="currentColor" />
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Home: bento of 3 entry points (dark hero + two preview cards) ──
function HubHome({
  id,
  pending,
  existing,
  onNew,
  onPending,
  onExisting,
}: {
  id: string;
  pending: SessionListItem[];
  existing: SessionListItem[];
  onNew: () => void;
  onPending: () => void;
  onExisting: () => void;
}) {
  const pendPreview = pending.slice(0, 3);
  const pubPreview = existing.slice(0, 2);
  return (
    <div className="mz-bento">
      {/* Primary — Start a new role (dark hero) */}
      <button id={`${id}-new`} type="button" className="mz-hero-card" onClick={onNew}>
        <div className="mz-hero-glow" aria-hidden="true" />
        <div className="mz-hero-orb" aria-hidden="true">
          <Orb size={150} state="listening" motion={true} />
        </div>
        <div className="mz-hero-inner">
          <div className="mz-hero-top">
            <div className="mz-hero-icon">
              <Sparkles size={20} color="currentColor" />
            </div>
          </div>
          <div className="mz-hero-mid">
            <h3 className="mz-hero-title">
              Start a<br />
              new role
            </h3>
            <p className="mz-hero-body">
              Give OpenRecruiting the role context and jump straight into the intake call.
            </p>
          </div>
          <div className="mz-hero-foot">
            <span className="mz-hero-cta">
              Begin intake
              <MoveRight size={17} color="currentColor" />
            </span>
            <div className="mz-hero-meta">
              <span>
                <Mic size={12} color="currentColor" />
                Voice or text
              </span>
              <span>
                <ClipboardCheck size={12} color="currentColor" />9 goals
              </span>
              <span>
                <Clock size={12} color="currentColor" />
                ~10 min
              </span>
            </div>
          </div>
        </div>
      </button>

      <div className="mz-bento-side">
        {/* Continue pending */}
        <button id={`${id}-pending`} type="button" className="mz-bento-card" onClick={onPending}>
          <div className="mz-bento-head">
            <div className="mz-bento-icon">
              <Clock size={18} color="var(--cortex-600)" />
            </div>
            <div className="mz-bento-headtext">
              <div className="mz-bento-titlerow">
                <h3 className="mz-bento-title">Continue pending</h3>
                <span className="mz-bento-count">{pending.length}</span>
              </div>
              <p className="mz-bento-body">Pick up an intake exactly where you left off.</p>
            </div>
            <span className="mz-bento-arrow">
              <ArrowRight size={16} />
            </span>
          </div>
          {pendPreview.length > 0 && (
            <div className="mz-bento-preview">
              {pendPreview.map((s) => (
                <div key={s.session_id} className="mz-prev-row">
                  <ProgressRing value={s.covered ?? 0} total={s.total || 9} size={26} stroke={3} />
                  <span className="mz-prev-role">{s.role_name ?? s.title}</span>
                  <span className="mz-prev-meta">
                    {s.covered ?? 0}/{s.total || 9} · {fmtRelative(s.last_activity_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </button>

        {/* Edit existing */}
        <button id={`${id}-existing`} type="button" className="mz-bento-card" onClick={onExisting}>
          <div className="mz-bento-head">
            <div className="mz-bento-icon">
              <ClipboardCheck size={18} color="var(--cortex-600)" />
            </div>
            <div className="mz-bento-headtext">
              <div className="mz-bento-titlerow">
                <h3 className="mz-bento-title">Edit existing</h3>
                <span className="mz-bento-count">{existing.length}</span>
              </div>
              <p className="mz-bento-body">Open a published role and refine its interview plan.</p>
            </div>
            <span className="mz-bento-arrow">
              <ArrowRight size={16} />
            </span>
          </div>
          {pubPreview.length > 0 && (
            <div className="mz-bento-preview">
              {pubPreview.map((s) => (
                <div key={s.session_id} className="mz-prev-row">
                  <span className="mz-prev-dot" />
                  <span className="mz-prev-role">{s.role_name ?? s.title}</span>
                  <span className="mz-prev-meta">
                    {s.rounds_count} rounds · {s.candidates_count} candidates
                  </span>
                </div>
              ))}
            </div>
          )}
        </button>
      </div>
    </div>
  );
}

// ── Pending row (resume intake) ──
function PendingRow({ id, s, onClick }: { id: string; s: SessionListItem; onClick: () => void }) {
  return (
    <button id={id} type="button" className="mz-list-row" onClick={onClick}>
      <ProgressRing value={s.covered ?? 0} total={s.total || 9} size={44} stroke={3.5} />
      <div className="mz-list-main">
        <div className="mz-list-toprow">
          <span className="mz-list-role">{s.role_name ?? s.title}</span>
        </div>
        <div className="mz-list-meta">
          {expLocation(s)}
          {s.stopped_at ? (
            <span className="mz-list-stop">
              <span className="mz-list-stopdot" />
              paused at {s.stopped_at}
            </span>
          ) : null}
        </div>
      </div>
      <div className="mz-list-right">
        <div className="mz-list-when">
          <Clock size={12} color="var(--text-faint)" />
          {fmtRelative(s.last_activity_at)}
        </div>
        <span className="mz-btn-dark mz-btn-sm">
          Resume
          <MoveRight size={15} color="currentColor" />
        </span>
      </div>
    </button>
  );
}

// ── Published row (edit plan) ──
function PublishedRow({ id, s, onClick }: { id: string; s: SessionListItem; onClick: () => void }) {
  const meta = [
    expLocation(s),
    `${s.rounds_count} rounds`,
    fmtDur(s.total_minutes),
    `${s.candidates_count} candidates`,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <button id={id} type="button" className="mz-list-row" onClick={onClick}>
      <div className="mz-list-badge">
        <ClipboardCheck size={18} color="var(--cortex-600)" />
      </div>
      <div className="mz-list-main">
        <div className="mz-list-toprow">
          <span className="mz-list-role">{s.role_name ?? s.title}</span>
          <span className="mz-cat mz-cat-success">
            <span className="mz-cand-dot" style={{ background: 'var(--status-success-fg)' }} />
            Planned
          </span>
        </div>
        <div className="mz-list-meta">{meta}</div>
      </div>
      <div className="mz-list-right">
        <div className="mz-list-when">
          <Clock size={12} color="var(--text-faint)" />
          {fmtRelative(s.last_activity_at)}
        </div>
        <span className="mz-btn-ghost mz-btn-sm">
          Edit plan
          <Pencil size={13} color="currentColor" />
        </span>
      </div>
    </button>
  );
}

interface HubProps {
  id: string;
}

export function Hub({ id }: HubProps) {
  const router = useRouter();
  const setSessionId = useIntakeStore((st) => st.setSessionId);
  const setPendingTransition = useIntakeStore((st) => st.setPendingTransition);
  const setEditPlanSession = useIntakeStore((st) => st.setEditPlanSession);
  const { sessions, isLoading } = useIntakeSessionsList();

  const [view, setView] = useState<'home' | 'pending' | 'existing'>('home');
  const [modalOpen, setModalOpen] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const pending = useMemo(
    () => sessions.filter((s) => s.display_status !== 'completed'),
    [sessions],
  );
  const existing = useMemo(
    () => sessions.filter((s) => s.display_status === 'completed'),
    [sessions],
  );

  const startNew = async (f: {
    roleName: string;
    expMin: number;
    expMax: number | null;
    location: string;
    jd: string;
  }) => {
    setStartError(null);
    try {
      const { session_id } = await createIntakeSession({
        form_data: {
          role_name: f.roleName,
          experience_min: f.expMin,
          experience_max: f.expMax,
          location: f.location,
          jd_text: f.jd ? f.jd : null,
        },
        entry_point: 'create_role_btn',
      });
      setSessionId(session_id);
      setPendingTransition('prefilling', 3000);
      router.push(`/intake/sessions/${session_id}`);
    } catch (err) {
      const detail =
        err instanceof IntakeApiError ? err.detail : err instanceof Error ? err.message : 'failed';
      setStartError(detail);
      setModalOpen(false);
    }
  };

  const resume = (s: SessionListItem) => {
    setSessionId(s.session_id);
    router.push(`/intake/sessions/${s.session_id}`);
  };

  const editPlan = (s: SessionListItem) => {
    setEditPlanSession(s.session_id);
    setSessionId(s.session_id);
    router.push(`/intake/sessions/${s.session_id}`);
  };

  const back = (
    <button
      id={`${id}-back`}
      type="button"
      className="mz-list-back"
      onClick={() => setView('home')}
    >
      <ArrowLeft size={15} /> All options
    </button>
  );

  return (
    <div id={id} className="mz-hub">
      <div className="mz-hub-scroll">
        <div className="mz-hub-inner">
          {view === 'home' && (
            <>
              <div className="mz-hub-head">
                <div className="mz-eyebrow">Intake</div>
                <h2 id={`${id}-title`} className="mz-hub-title">
                  What are we working on?
                </h2>
              </div>
              {isLoading && sessions.length === 0 ? (
                <IntakeHubSkeleton id={`${id}-home-skeleton`} />
              ) : (
                <HubHome
                  id={`${id}-home`}
                  pending={pending}
                  existing={existing}
                  onNew={() => setModalOpen(true)}
                  onPending={() => setView('pending')}
                  onExisting={() => setView('existing')}
                />
              )}
              {startError && (
                <div
                  id={`${id}-start-error`}
                  role="alert"
                  className="mt-4 text-sm text-[var(--danger-fg)]"
                >
                  {startError}
                </div>
              )}
            </>
          )}

          {view === 'pending' && (
            <>
              {back}
              <div className="mz-list-head">
                <div>
                  <div className="mz-eyebrow">Continue pending</div>
                  <h2 className="mz-list-title">Resume an intake</h2>
                </div>
                <span className="mz-list-counter">{pending.length} pending</span>
              </div>
              {pending.length === 0 ? (
                <p id={`${id}-pending-empty`} className="text-sm text-[var(--text-muted)]">
                  No intakes in progress. Start a new role to begin.
                </p>
              ) : (
                <div className="mz-list">
                  {pending.map((s) => (
                    <PendingRow
                      id={`${id}-pending-${s.session_id}`}
                      key={s.session_id}
                      s={s}
                      onClick={() => resume(s)}
                    />
                  ))}
                </div>
              )}
            </>
          )}

          {view === 'existing' && (
            <>
              {back}
              <div className="mz-list-head">
                <div>
                  <div className="mz-eyebrow">Edit existing</div>
                  <h2 className="mz-list-title">Published roles</h2>
                </div>
                <span className="mz-list-counter">{existing.length} roles</span>
              </div>
              {existing.length === 0 ? (
                <p id={`${id}-existing-empty`} className="text-sm text-[var(--text-muted)]">
                  No published roles yet. Finish an intake to publish a plan.
                </p>
              ) : (
                <div className="mz-list">
                  {existing.map((s) => (
                    <PublishedRow
                      id={`${id}-existing-${s.session_id}`}
                      key={s.session_id}
                      s={s}
                      onClick={() => editPlan(s)}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {modalOpen && (
        <NewRoleModal id={`${id}-newrole`} onClose={() => setModalOpen(false)} onStart={startNew} />
      )}
    </div>
  );
}
