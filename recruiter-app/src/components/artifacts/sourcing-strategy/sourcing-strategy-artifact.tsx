'use client';

import {
  Briefcase,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
  FileText,
  Loader2,
  MapPin,
  Share2,
  Sparkles,
  Users,
} from 'lucide-react';
import { memo, useState } from 'react';
import { cn, pickAvatarFg } from '@/lib/utils';
import { ThinkingTrailHeader, ThinkingTrailPanel } from '../_shared/thinking-trail';
import { useTypedArtifact } from '../_shared/use-artifact-data';
import type {
  SourcingChannel,
  SourcingStrategyArtifactData,
  SourcingStrategyCandidate,
  SourcingStrategyPhase,
  SourcingStrategyTab,
  SourcingTrailStep,
} from './types';

export interface SourcingStrategyArtifactProps {
  id: string;
  artifactId: string;
  onToggleCandidate?: (candidateId: string) => void;
  onAddSelectedToPipeline?: () => void;
  onBackToRole?: () => void;
  onShareStrategy?: () => void;
  onDownloadStrategy?: () => void;
  onSwitchTab?: (tab: SourcingStrategyTab) => void;
}

const DRAFT_STEP_ORDER = [
  'draft-parse-role',
  'draft-parse-prefs',
  'draft-icp',
  'draft-dedupe',
  'draft-doc',
];

function computeDraftProgress(steps: SourcingStrategyArtifactData['trailSteps']): number {
  let done = 0;
  for (const stepId of DRAFT_STEP_ORDER) {
    const step = steps.find((s) => s.id === stepId);
    if (step?.status === 'done') done += 1;
    else break;
  }
  return done;
}

export function SourcingStrategyArtifact({
  id,
  artifactId,
  onToggleCandidate,
  onAddSelectedToPipeline,
  onBackToRole,
  onShareStrategy,
  onDownloadStrategy,
  onSwitchTab,
}: SourcingStrategyArtifactProps) {
  const artifact = useTypedArtifact(artifactId, 'sourcing-strategy');
  const [shareCopied, setShareCopied] = useState(false);

  if (!artifact) return null;
  const data = artifact.data;
  if (!data?.icp) {
    return (
      <div id={id} className="animate-pulse pt-2 text-[12.5px] text-text-muted">
        Drafting sourcing strategy…
      </div>
    );
  }

  const activeTab = data.activeTab ?? 'strategy';
  const candidateCount = data.candidates.length;
  const scannedChannels = data.channels.filter((c) => c.status === 'done').length;

  const handleShare = () => {
    setShareCopied(true);
    setTimeout(() => setShareCopied(false), 1800);
    onShareStrategy?.();
  };

  return (
    <div id={id} className="flex flex-col gap-5 pb-10">
      {/* Toolbar — actions + phase banner. Headlines live inside each tab. */}
      <header id={`${id}-hero`} className="flex flex-wrap items-center justify-between gap-3">
        <PhaseBanner id={`${id}-phase`} phase={data.phase} label={data.totalProfilesLabel} />
        <div className="flex items-center gap-1.5">
          <button
            id={`${id}-share`}
            type="button"
            onClick={handleShare}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-3 py-1.5 font-medium font-sans text-[12px] text-text-primary transition hover:border-text-primary"
          >
            {shareCopied ? (
              <>
                <Check strokeWidth={2} className="h-3.5 w-3.5 text-[#047857]" />
                Link copied
              </>
            ) : (
              <>
                <Share2 strokeWidth={1.75} className="h-3.5 w-3.5" />
                Share
              </>
            )}
          </button>
          <button
            id={`${id}-download`}
            type="button"
            onClick={() => onDownloadStrategy?.()}
            aria-label="Download strategy"
            className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-border bg-white text-text-muted transition hover:border-text-primary hover:text-text-primary"
          >
            <Download strokeWidth={1.75} className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      {/* Tabs */}
      <div id={`${id}-tabs`} role="tablist" className="flex gap-1 rounded-[12px] bg-surface p-1">
        <TabButton
          id={`${id}-tab-strategy`}
          label="Strategy"
          icon={<FileText strokeWidth={1.75} className="h-3.5 w-3.5" />}
          active={activeTab === 'strategy'}
          onClick={() => onSwitchTab?.('strategy')}
        />
        <TabButton
          id={`${id}-tab-candidates`}
          label={
            <>
              Candidates
              {candidateCount > 0 && (
                <span className="ml-1.5 rounded-full bg-text-primary/10 px-1.5 py-0.5 font-mono text-[9.5px] text-text-primary">
                  {candidateCount}
                </span>
              )}
            </>
          }
          icon={<Users strokeWidth={1.75} className="h-3.5 w-3.5" />}
          active={activeTab === 'candidates'}
          onClick={() => onSwitchTab?.('candidates')}
          pulse={data.phase === 'scanning' || data.phase === 'ranking'}
        />
      </div>

      {activeTab === 'strategy' ? (
        <StrategyTab
          id={`${id}-strategy`}
          data={data}
          onViewCandidates={() => onSwitchTab?.('candidates')}
        />
      ) : (
        <CandidatesTab
          id={`${id}-candidates-tab`}
          data={data}
          scannedChannels={scannedChannels}
          onToggleCandidate={onToggleCandidate}
          onAddSelectedToPipeline={onAddSelectedToPipeline}
          onBackToRole={onBackToRole}
        />
      )}
    </div>
  );
}

function TabButton({
  id,
  label,
  icon,
  active,
  onClick,
  pulse = false,
}: {
  id: string;
  label: React.ReactNode;
  icon: React.ReactNode;
  active: boolean;
  onClick: () => void;
  pulse?: boolean;
}) {
  return (
    <button
      id={id}
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        'relative flex flex-1 items-center justify-center gap-1.5 rounded-[10px] px-3 py-1.5 font-medium font-sans text-[12.5px] transition-colors',
        active
          ? 'bg-white text-text-primary shadow-[0_1px_3px_rgba(0,0,0,0.04)]'
          : 'text-text-muted hover:text-text-primary',
      )}
    >
      {icon}
      {label}
      {pulse && !active && (
        <span
          aria-hidden
          className="absolute top-1.5 right-2 inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-cortex-500"
        />
      )}
    </button>
  );
}

/* ---------- Strategy tab ---------- */

type StrategySectionKey =
  | 'location'
  | 'seniority'
  | 'experience'
  | 'must_haves'
  | 'nice_to_haves'
  | 'target_companies'
  | 'red_flags'
  | 'calibration';

const STRATEGY_SECTIONS: Array<{
  key: StrategySectionKey;
  label: string;
  revealAt: number;
  fullWidth?: boolean;
}> = [
  { key: 'location', label: 'Location', revealAt: 3 },
  { key: 'seniority', label: 'Seniority', revealAt: 3 },
  { key: 'experience', label: 'Experience requirements', revealAt: 3, fullWidth: true },
  { key: 'must_haves', label: 'Must-haves', revealAt: 4, fullWidth: true },
  { key: 'nice_to_haves', label: 'Nice-to-haves', revealAt: 4, fullWidth: true },
  { key: 'target_companies', label: 'Target companies', revealAt: 5, fullWidth: true },
  { key: 'red_flags', label: 'Red flags', revealAt: 5, fullWidth: true },
  { key: 'calibration', label: 'Role calibration note', revealAt: 5, fullWidth: true },
];

function StrategyTab({
  id,
  data,
  onViewCandidates,
}: {
  id: string;
  data: SourcingStrategyArtifactData;
  onViewCandidates: () => void;
}) {
  const draftProgress = computeDraftProgress(data.trailSteps);
  const isDrafting = data.phase === 'drafting';
  const candidatesReady = data.phase === 'awaiting_selection' || data.phase === 'added';
  const candidateCount = data.candidates.length;

  return (
    <section id={id} aria-label="Sourcing strategy" className="flex min-w-0 flex-col">
      <header id={`${id}-head`} className="mb-5 border-border border-b pb-4">
        <div
          id={`${id}-eyebrow`}
          className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
        >
          OpenRecruiting&apos;s read · Sourcing plan
        </div>
        <h2
          id={`${id}-headline`}
          className="mt-2 font-display text-[28px] text-text-primary leading-tight tracking-[-0.01em]"
        >
          Sourcing plan for{' '}
          <em id={`${id}-headline-role`} className="font-display italic">
            {data.roleTitle ?? 'this role'}
          </em>
          , across {data.channels.length} channels.
        </h2>
        <p
          id={`${id}-sub`}
          className="mt-2 max-w-[640px] text-[13.5px] text-text-secondary leading-[1.55]"
        >
          Built from your intake and preferences. Targeting{' '}
          <b className="font-medium text-text-primary">{data.totalProfilesLabel.toLowerCase()}</b>{' '}
          this week across LinkedIn Recruiter, Greenhouse talent pool, warm referrals, and
          Wellfound.
        </p>
        <div
          id={`${id}-meta`}
          className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]"
        >
          <span>Owned by {data.ownerName}</span>
          <span aria-hidden>·</span>
          <span>{data.createdAtLabel}</span>
          {data.savedToRole && (
            <>
              <span aria-hidden>·</span>
              <span className="inline-flex items-center gap-1 text-[#047857]">
                <Check strokeWidth={2} className="h-3 w-3" />
                Saved to role
              </span>
            </>
          )}
        </div>
      </header>

      {data.userPreferences && (
        <div
          id={`${id}-prefs`}
          className="mb-3 rounded-[14px] border border-[#FDE68A] bg-[#FFFBEB]/70 p-4"
        >
          <div className="mb-1 font-mono text-[#B45309] text-[9.5px] uppercase tracking-[0.14em]">
            Your preferences
          </div>
          <p className="text-[#7A4A0A] text-[13px] leading-[1.55]">{data.userPreferences}</p>
        </div>
      )}

      {data.icp && (
        <div
          id={`${id}-icp-summary`}
          className="mb-3 rounded-[14px] border border-border/70 bg-white/85 p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm"
        >
          <div
            id={`${id}-icp-summary-label`}
            className="mb-1.5 font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]"
          >
            Ideal candidate
          </div>
          <p className="font-sans text-[13px] text-text-secondary leading-[1.55]">{data.icp}</p>
        </div>
      )}

      <div id={`${id}-grid`} className="grid gap-3 md:grid-cols-2">
        {STRATEGY_SECTIONS.map((section) => {
          const revealed = draftProgress >= section.revealAt;
          const fullWidth = section.fullWidth ?? false;
          const sectionId = `${id}-sec-${section.key}`;
          if (!revealed) {
            return (
              <StrategySectionCard
                key={section.key}
                id={sectionId}
                label={section.label}
                revealed={false}
                fullWidth={fullWidth}
              />
            );
          }
          return (
            <StrategySectionCard
              key={section.key}
              id={sectionId}
              label={section.label}
              revealed
              fullWidth={fullWidth}
            >
              <StrategySectionBody id={sectionId} sectionKey={section.key} data={data} />
            </StrategySectionCard>
          );
        })}
      </div>

      {data.trailVisible && (
        <div className="mt-4">
          <ThinkingTrail id={`${id}-trail`} steps={data.trailSteps} phase={data.phase} />
        </div>
      )}

      {candidatesReady && (
        <div
          id={`${id}-candidates-cta`}
          className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-[14px] border border-[#A7F3D0] bg-[#ECFDF5]/70 p-4"
        >
          <div className="min-w-0">
            <div className="font-medium font-sans text-[13px] text-text-primary">
              {candidateCount} candidate{candidateCount === 1 ? '' : 's'} ready to review
            </div>
            <div className="mt-0.5 text-[12px] text-text-secondary leading-[1.5]">
              Top matches across LinkedIn, Greenhouse, referrals, and Wellfound — tap to review and
              add them to the pipeline.
            </div>
          </div>
          <button
            id={`${id}-view-candidates`}
            type="button"
            onClick={onViewCandidates}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-4 py-2 font-medium font-sans text-[12.5px] text-white hover:bg-[#222]"
          >
            <Users strokeWidth={2} className="h-3.5 w-3.5" />
            View {candidateCount} candidate{candidateCount === 1 ? '' : 's'}
          </button>
        </div>
      )}

      {isDrafting && draftProgress < STRATEGY_SECTIONS.length && (
        <p
          id={`${id}-drafting-note`}
          className="mt-4 text-center font-mono text-[10px] text-text-muted uppercase tracking-[0.18em]"
        >
          OpenRecruiting is writing this plan in real time — watch the trail below.
        </p>
      )}
    </section>
  );
}

function StrategySectionCard({
  id,
  label,
  revealed,
  fullWidth = false,
  children,
}: {
  id: string;
  label: string;
  revealed: boolean;
  fullWidth?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <article
      id={id}
      className={cn(
        'rounded-[14px] border border-border/70 bg-white/85 p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm',
        fullWidth && 'md:col-span-2',
      )}
    >
      <div
        id={`${id}-label`}
        className="mb-1.5 font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]"
      >
        {label}
      </div>
      {revealed ? (
        <div id={`${id}-body`} className="font-sans text-[13px] text-text-secondary leading-[1.55]">
          {children}
        </div>
      ) : (
        <ShimmerLines />
      )}
    </article>
  );
}

function StrategySectionBody({
  id,
  sectionKey,
  data,
}: {
  id: string;
  sectionKey: StrategySectionKey;
  data: SourcingStrategyArtifactData;
}) {
  switch (sectionKey) {
    case 'location':
      return <p id={`${id}-text`}>{data.location}</p>;
    case 'seniority':
      return <p id={`${id}-text`}>{data.seniority}</p>;
    case 'experience':
      return <BulletList id={`${id}-list`} items={data.experienceRequirements} />;
    case 'must_haves':
      return <BulletList id={`${id}-list`} items={data.mustHaves} emphasis="primary" />;
    case 'nice_to_haves':
      return <BulletList id={`${id}-list`} items={data.niceToHaves} />;
    case 'target_companies':
      return <TargetCompanyTiers id={`${id}-tiers`} tiers={data.targetCompanyTiers} />;
    case 'red_flags':
      return <BulletList id={`${id}-list`} items={data.redFlags} emphasis="warning" />;
    case 'calibration':
      return (
        <p id={`${id}-text`} className="italic leading-[1.6]">
          {data.calibrationNote}
        </p>
      );
  }
}

function BulletList({
  id,
  items,
  emphasis,
}: {
  id: string;
  items: string[];
  emphasis?: 'primary' | 'warning';
}) {
  if (items.length === 0) return null;
  const dotClass =
    emphasis === 'primary'
      ? 'bg-text-primary'
      : emphasis === 'warning'
        ? 'bg-[#B45309]'
        : 'bg-text-muted';
  return (
    <ul id={id} className="flex flex-col gap-1.5">
      {items.map((item, i) => (
        <li
          // biome-ignore lint/suspicious/noArrayIndexKey: list is a stable authored fixture
          key={i}
          id={`${id}-item-${i}`}
          className="flex items-start gap-2"
        >
          <span
            aria-hidden
            className={cn('mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full', dotClass)}
          />
          <span className="min-w-0 flex-1">{item}</span>
        </li>
      ))}
    </ul>
  );
}

function TargetCompanyTiers({
  id,
  tiers,
}: {
  id: string;
  tiers: SourcingStrategyArtifactData['targetCompanyTiers'];
}) {
  if (tiers.length === 0) return null;
  const TIER_STYLE: Record<
    SourcingStrategyArtifactData['targetCompanyTiers'][number]['tier'],
    { label: string; chip: string; dot: string }
  > = {
    primary: {
      label: 'Primary',
      chip: 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]',
      dot: 'bg-[#047857]',
    },
    secondary: {
      label: 'Secondary',
      chip: 'border-[#BFDBFE] bg-[#EFF6FF] text-[#1E40AF]',
      dot: 'bg-[#1E40AF]',
    },
    tertiary: {
      label: 'Tertiary',
      chip: 'border-border bg-surface text-text-secondary',
      dot: 'bg-text-muted',
    },
  };
  return (
    <div id={id} className="flex flex-col gap-3">
      {tiers.map((tier) => {
        const style = TIER_STYLE[tier.tier];
        return (
          <section
            key={tier.tier}
            id={`${id}-${tier.tier}`}
            className="rounded-[12px] border border-border bg-surface/40 p-3"
          >
            <header className="mb-2 flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium font-mono text-[10px] uppercase tracking-[0.14em]',
                  style.chip,
                )}
              >
                <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', style.dot)} />
                {style.label}
              </span>
              <div className="min-w-0 font-medium text-[12.5px] text-text-primary">
                {tier.label}
              </div>
              <div className="ml-auto font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                {tier.note}
              </div>
            </header>
            <ul className="flex flex-wrap gap-1.5">
              {tier.companies.map((company) => (
                <li
                  key={company}
                  className="inline-flex items-center rounded-full border border-border bg-white px-2.5 py-0.5 font-medium text-[11.5px] text-text-secondary"
                >
                  {company}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function ShimmerLines() {
  return (
    <div aria-hidden className="flex flex-col gap-2 pt-1">
      <div className="h-3 w-[92%] animate-pulse rounded bg-surface" />
      <div className="h-3 w-[78%] animate-pulse rounded bg-surface" />
      <div className="h-3 w-[58%] animate-pulse rounded bg-surface" />
    </div>
  );
}

/* ---------- Candidates tab ---------- */

function CandidatesTab({
  id,
  data,
  scannedChannels,
  onToggleCandidate,
  onAddSelectedToPipeline,
  onBackToRole,
}: {
  id: string;
  data: SourcingStrategyArtifactData;
  scannedChannels: number;
  onToggleCandidate?: ((candidateId: string) => void) | undefined;
  onAddSelectedToPipeline?: (() => void) | undefined;
  onBackToRole?: (() => void) | undefined;
}) {
  const phase = data.phase;
  const selectedCount = data.selectedCandidateIds.length;
  const showAddCTA = phase === 'awaiting_selection' && data.candidates.length > 0;
  const alreadyAdded = phase === 'added';
  const stillWorking = phase === 'scanning' || phase === 'ranking';

  return (
    <div id={id} className="flex flex-col gap-4">
      {data.trailVisible && (
        <ThinkingTrail id={`${id}-trail`} steps={data.trailSteps} phase={data.phase} />
      )}

      <section id={`${id}-channels`} className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
            Channels · {scannedChannels} of {data.channels.length} done
          </span>
          {phase === 'scanning' && (
            <span className="inline-flex items-center gap-1.5 font-mono text-[10.5px] text-cortex-500 uppercase tracking-[0.14em]">
              <Loader2 strokeWidth={2} className="h-3 w-3 animate-spin" />
              Sourcing…
            </span>
          )}
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {data.channels.map((ch) => (
            <ChannelCard key={ch.id} id={`${id}-channel-${ch.id}`} channel={ch} />
          ))}
        </div>
      </section>

      <section id={`${id}-list`} className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
            {stillWorking
              ? `Streaming matches · ${data.candidates.length} so far`
              : `Top matches · ${data.candidates.length}`}
          </span>
          {showAddCTA && (
            <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
              {selectedCount} selected
            </span>
          )}
        </div>

        {data.candidates.length === 0 && <CandidateSkeletonList id={`${id}-skeleton`} />}

        <ul className="flex flex-col gap-2">
          {data.candidates.map((c) => (
            <CandidateCard
              key={c.id}
              id={`${id}-cand-${c.id}`}
              candidate={c}
              selected={data.selectedCandidateIds.includes(c.id)}
              selectable={phase === 'awaiting_selection'}
              onToggle={() => onToggleCandidate?.(c.id)}
            />
          ))}
          {stillWorking && data.candidates.length > 0 && (
            <li
              id={`${id}-loading-row`}
              className="inline-flex items-center gap-2 rounded-[14px] border border-border border-dashed bg-white/60 p-3 text-[12px] text-text-muted"
            >
              <Loader2 strokeWidth={1.75} className="h-3.5 w-3.5 animate-spin" />
              Matching more profiles…
            </li>
          )}
        </ul>

        {(showAddCTA || alreadyAdded) && (
          <footer className="flex items-center justify-between gap-3 border-border border-t pt-3">
            {showAddCTA && (
              <>
                <span className="text-[12px] text-text-muted">
                  {data.roleId ? (
                    <>
                      Checked candidates will be added to{' '}
                      <span className="font-medium text-text-primary">
                        {data.roleTitle ?? 'the role'}
                      </span>{' '}
                      at stage <span className="font-medium text-text-primary">applied</span>.
                    </>
                  ) : (
                    <>
                      No role bound yet — I'll spin up a new role named{' '}
                      <span className="font-medium text-text-primary">
                        "{data.roleTitle ?? 'Sourced role'}"
                      </span>{' '}
                      and drop the checked candidates into its pipeline.
                    </>
                  )}
                </span>
                <button
                  id={`${id}-add-selected`}
                  type="button"
                  onClick={() => onAddSelectedToPipeline?.()}
                  disabled={selectedCount === 0}
                  className={cn(
                    'inline-flex shrink-0 items-center gap-1.5 rounded-full px-4 py-2 font-medium text-[12.5px] transition-colors',
                    selectedCount === 0
                      ? 'cursor-not-allowed border border-border bg-surface text-text-faint'
                      : 'border border-text-primary bg-text-primary text-white hover:bg-[#222]',
                  )}
                >
                  <Check strokeWidth={2} className="h-3.5 w-3.5" />
                  {data.roleId
                    ? `Add ${selectedCount} to ${data.roleTitle ?? 'pipeline'}`
                    : `Create role & add ${selectedCount}`}
                </button>
              </>
            )}
            {alreadyAdded && (
              <>
                <span className="inline-flex items-center gap-1.5 text-[#047857] text-[12.5px]">
                  <Check strokeWidth={2} className="h-3.5 w-3.5" />
                  {data.addedCount} added to pipeline
                </span>
                <button
                  id={`${id}-back-to-role`}
                  type="button"
                  onClick={() => onBackToRole?.()}
                  className="inline-flex items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-4 py-2 font-medium text-[12.5px] text-white hover:bg-[#222]"
                >
                  See the role · schedule interviews
                </button>
              </>
            )}
          </footer>
        )}
      </section>
    </div>
  );
}

/* ---------- Sub-components ---------- */

function PhaseBanner({
  id,
  phase,
  label,
}: {
  id: string;
  phase: SourcingStrategyPhase;
  label: string;
}) {
  const meta: Record<SourcingStrategyPhase, { text: string; cls: string; icon: React.ReactNode }> =
    {
      drafting: {
        text: 'Drafting your sourcing strategy…',
        cls: 'border-[#BFDBFE] bg-[#EFF6FF] text-[#1D4ED8]',
        icon: <Loader2 strokeWidth={2} className="h-3.5 w-3.5 animate-spin" />,
      },
      scanning: {
        text: 'Scanning channels for matching profiles…',
        cls: 'border-[#BFDBFE] bg-[#EFF6FF] text-[#1D4ED8]',
        icon: <Loader2 strokeWidth={2} className="h-3.5 w-3.5 animate-spin" />,
      },
      ranking: {
        text: 'Ranking shortlist against the ICP…',
        cls: 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]',
        icon: <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5" />,
      },
      awaiting_selection: {
        text: `${label} · pick the ones to move forward`,
        cls: 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]',
        icon: <Check strokeWidth={2} className="h-3.5 w-3.5" />,
      },
      added: {
        text: 'Candidates added — pipeline updated',
        cls: 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]',
        icon: <Check strokeWidth={2} className="h-3.5 w-3.5" />,
      },
    };
  const m = meta[phase];
  return (
    <div
      id={id}
      className={cn(
        'inline-flex w-fit items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em]',
        m.cls,
      )}
    >
      {m.icon}
      {m.text}
    </div>
  );
}

function ThinkingTrail({
  id,
  steps,
  phase,
}: {
  id: string;
  steps: SourcingTrailStep[];
  phase: SourcingStrategyPhase;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const doneAll = steps.every((s) => s.status === 'done');
  const label =
    phase === 'drafting'
      ? 'Agent · drafting strategy'
      : phase === 'scanning'
        ? 'Agent · scanning channels'
        : phase === 'ranking'
          ? 'Agent · ranking shortlist'
          : 'Agent · done';
  return (
    <ThinkingTrailPanel id={id} className="shadow-[0_6px_18px_rgba(15,22,32,0.2)]">
      <ThinkingTrailHeader
        label={label}
        dot={doneAll ? 'none' : 'pulse'}
        onToggle={() => setCollapsed((v) => !v)}
        className="border-[rgba(200,212,227,0.2)] border-b px-4 py-2.5"
        status={
          <span className="text-[rgba(200,212,227,0.6)] inline-flex items-center gap-2">
            {steps.filter((s) => s.status === 'done').length}/{steps.length}
            {collapsed ? (
              <ChevronDown strokeWidth={1.75} className="h-3 w-3" />
            ) : (
              <ChevronUp strokeWidth={1.75} className="h-3 w-3" />
            )}
          </span>
        }
      />
      {!collapsed && (
        <ol className="flex flex-col gap-0 p-4 font-mono text-[11.5px] leading-[1.55]">
          {steps.map((s, i) => (
            <li
              key={s.id}
              id={`${id}-step-${s.id}`}
              className={cn(
                'grid grid-cols-[22px_1fr] gap-2 border-[rgba(200,212,227,0.08)] border-b border-dotted py-1.5 last:border-b-0',
                s.status === 'running' && 'text-[#F2B79A]',
                s.status === 'pending' && 'text-[rgba(200,212,227,0.4)]',
              )}
            >
              <span className="pt-[3px] text-[9.5px] tabular-nums">
                {s.status === 'done' ? (
                  <Check strokeWidth={2.5} className="h-3 w-3 text-[#8DD18D]" />
                ) : s.status === 'running' ? (
                  <Loader2 strokeWidth={2} className="h-3 w-3 animate-spin" />
                ) : (
                  String(i + 1).padStart(2, '0')
                )}
              </span>
              <span>
                <span className={cn(s.status === 'done' && 'text-[#C8D4E3]')}>{s.body}</span>
                {s.detail && (
                  <span className="ml-1 text-[rgba(200,212,227,0.55)]">· {s.detail}</span>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
    </ThinkingTrailPanel>
  );
}

const ChannelCard = memo(function ChannelCardInner({
  id,
  channel,
}: {
  id: string;
  channel: SourcingChannel;
}) {
  const pct =
    channel.totalTarget === 0
      ? channel.status === 'done'
        ? 100
        : 0
      : Math.min(100, Math.round((channel.scanned / channel.totalTarget) * 100));
  return (
    <article
      id={id}
      className={cn(
        'rounded-[14px] border bg-white p-4 transition-colors',
        channel.status === 'scanning' && 'border-[#BFDBFE] bg-[#EFF6FF]/30',
        channel.status === 'done' && 'border-[#A7F3D0]',
        channel.status === 'pending' && 'border-border',
      )}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] text-text-primary uppercase tracking-[0.14em]">
          {channel.name}
        </span>
        <ChannelStatusBadge status={channel.status} />
      </div>
      <div className="mt-1.5 font-display text-[26px] text-text-primary tabular-nums leading-none tracking-[-0.02em]">
        {channel.scanned.toLocaleString()}
        <span className="ml-1.5 font-sans text-[11.5px] text-text-muted">{channel.statLabel}</span>
      </div>
      <p className="mt-1 text-[11px] text-text-muted leading-[1.4]">
        {channel.status === 'pending'
          ? 'Queued to scan'
          : channel.status === 'scanning'
            ? `Scanning ${channel.totalTarget.toLocaleString()} profiles…`
            : channel.note}
      </p>
      <div aria-hidden className="mt-2.5 h-1 w-full overflow-hidden rounded-full bg-surface">
        <div
          className={cn(
            'h-full rounded-full transition-all duration-500',
            channel.status === 'done' ? 'bg-[#10B981]' : 'bg-[#1D4ED8]',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </article>
  );
});

function ChannelStatusBadge({ status }: { status: SourcingChannel['status'] }) {
  if (status === 'scanning') {
    return (
      <span className="inline-flex items-center gap-1 font-mono text-[#1D4ED8] text-[9.5px] uppercase tracking-[0.14em]">
        <Loader2 strokeWidth={2} className="h-3 w-3 animate-spin" />
        Scanning
      </span>
    );
  }
  if (status === 'done') {
    return (
      <span className="inline-flex items-center gap-1 font-mono text-[#047857] text-[9.5px] uppercase tracking-[0.14em]">
        <Check strokeWidth={2} className="h-3 w-3" />
        Done
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
      Queued
    </span>
  );
}

const CandidateCard = memo(function CandidateCardInner({
  id,
  candidate,
  selected,
  selectable,
  onToggle,
}: {
  id: string;
  candidate: SourcingStrategyCandidate;
  selected: boolean;
  selectable: boolean;
  onToggle: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <li
      id={id}
      className={cn(
        'rounded-[14px] border bg-white p-3.5 transition-colors',
        selected ? 'border-text-primary bg-surface/70' : 'border-border',
      )}
    >
      <div className="grid grid-cols-[auto_auto_auto_1fr_auto] items-start gap-3">
        <label
          className={cn(
            'mt-1.5 flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded-[6px] border transition-colors',
            selected
              ? 'border-text-primary bg-text-primary text-white'
              : 'border-border bg-white text-transparent',
            !selectable && 'cursor-not-allowed opacity-50',
          )}
        >
          <input
            type="checkbox"
            className="sr-only"
            checked={selected}
            disabled={!selectable}
            onChange={onToggle}
          />
          <Check strokeWidth={2.25} className="h-3 w-3" />
        </label>
        <span
          aria-hidden
          className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full font-medium font-mono text-[12px]"
          style={{ background: candidate.color, color: pickAvatarFg(candidate.color) }}
        >
          {candidate.initials}
        </span>
        <span
          aria-hidden
          className="mt-1.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-surface font-mono text-[10px] text-text-muted tabular-nums"
        >
          {candidate.rank}
        </span>
        <div className="min-w-0">
          <div className="truncate font-medium text-[13.5px] text-text-primary">
            {candidate.name}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-text-muted">
            <span className="inline-flex items-center gap-1">
              <Briefcase strokeWidth={1.75} className="h-3 w-3" />
              {candidate.title} · {candidate.company}
            </span>
            <span aria-hidden>·</span>
            <span className="inline-flex items-center gap-1">
              <MapPin strokeWidth={1.75} className="h-3 w-3" />
              {candidate.location}
            </span>
            <span aria-hidden>·</span>
            <span>{candidate.yearsLabel}</span>
            <span aria-hidden>·</span>
            <span>{candidate.industry}</span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1">
            <span className="inline-flex items-center rounded-full border border-[#BFDBFE] bg-[#EFF6FF] px-1.5 py-0.5 font-mono text-[#1D4ED8] text-[9px] uppercase tracking-[0.14em]">
              {candidate.sourceLabel}
            </span>
            {candidate.tags.map((t) => (
              <span
                key={t}
                className="inline-flex items-center rounded-full border border-border bg-surface px-1.5 py-0.5 font-mono text-[9px] text-text-muted uppercase tracking-[0.14em]"
              >
                {t}
              </span>
            ))}
          </div>
          {expanded && candidate.highlights.length > 0 && (
            <ul className="mt-2 flex flex-col gap-0.5 border-border border-t pt-2 text-[12px] text-text-muted">
              {candidate.highlights.map((h) => (
                <li key={h} className="flex gap-1.5">
                  <span aria-hidden className="text-text-faint">
                    ›
                  </span>
                  {h}
                </li>
              ))}
            </ul>
          )}
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-1.5 inline-flex items-center gap-1 font-mono text-[10px] text-text-muted uppercase tracking-[0.14em] hover:text-text-primary"
          >
            {expanded ? (
              <>
                <ChevronUp strokeWidth={1.75} className="h-3 w-3" />
                Hide profile
              </>
            ) : (
              <>
                <ChevronDown strokeWidth={1.75} className="h-3 w-3" />
                Profile & highlights
              </>
            )}
          </button>
        </div>
        <div className="text-right">
          <div className="font-display text-[24px] text-text-primary leading-none tracking-[-0.02em]">
            {candidate.score}
          </div>
          <div className="font-mono text-[9px] text-text-muted uppercase tracking-[0.14em]">
            match
          </div>
        </div>
      </div>
    </li>
  );
});

function CandidateSkeletonList({ id }: { id: string }) {
  return (
    <ul id={id} className="flex flex-col gap-2">
      {[0, 1, 2].map((i) => (
        <li
          key={i}
          className="grid grid-cols-[auto_auto_1fr_auto] items-center gap-3 rounded-[14px] border border-border bg-white/60 p-3.5"
        >
          <div className="h-5 w-5 animate-pulse rounded-[6px] bg-surface" />
          <div className="h-10 w-10 animate-pulse rounded-full bg-surface" />
          <div className="flex flex-col gap-1.5">
            <div className="h-3 w-40 animate-pulse rounded bg-surface" />
            <div className="h-2.5 w-56 animate-pulse rounded bg-surface" />
            <div className="h-2.5 w-32 animate-pulse rounded bg-surface" />
          </div>
          <div className="h-6 w-10 animate-pulse rounded bg-surface" />
        </li>
      ))}
    </ul>
  );
}
