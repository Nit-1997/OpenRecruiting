'use client';

import { Briefcase, Check, Loader2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { SkeletonLines } from '@/components/shell/primitives';
import { makeMessage } from '@/lib/sub-agent-runner';
import {
  useActiveContextStore,
  useArtifactStore,
  useRequisitionStore,
  useRoleStore,
  useSessionStore,
} from '@/stores';
import type { IntakeProcessingStage } from '@/types';
import { mirrorIntakeToDashboard } from './mirror-to-dashboard';
import { RoleSummary } from './role-summary';
import { RoundDetailView } from './round-detail-view';
import { RoundList } from './round-list';

export interface RequisitionArtifactProps {
  id: string;
  artifactId: string;
  onPublished?: (requisitionId: string) => void;
}

interface ChecklistItem {
  key: IntakeProcessingStage;
  label: string;
}

const CHECKLIST: ChecklistItem[] = [
  { key: 'summarizing', label: 'Analyzing your conversation' },
  { key: 'building_plan', label: 'Designing interview rounds' },
  { key: 'designing_rounds', label: 'Finalizing evaluation criteria' },
];

const STAGE_ORDER: Record<IntakeProcessingStage, number> = {
  summarizing: 0,
  building_plan: 1,
  designing_rounds: 2,
  completed: 3,
};

function experienceDisplay(min: number, max: number | null): string {
  if (max === null) return `${min}+ yrs`;
  if (min === max) return `${min} yrs`;
  return `${min}–${max} yrs`;
}

export function RequisitionArtifact({ id, artifactId }: RequisitionArtifactProps) {
  const req = useRequisitionStore((s) => s.requisitions[artifactId]);
  const publish = useRequisitionStore((s) => s.publish);
  const validatePublish = useRequisitionStore((s) => s.validatePublish);
  const [selectedRoundId, setSelectedRoundId] = useState<string | null>(null);
  const [savedAsDraft, setSavedAsDraft] = useState(false);
  const router = useRouter();

  if (!req) return null;

  const isBuilding = req.intakeProcessingStatus === 'processing';
  const currentStageIdx = req.intakeProcessingStage ? STAGE_ORDER[req.intakeProcessingStage] : -1;
  const isPublished = req.status === 'planned';
  const validation = validatePublish(req.id);
  const canPublish = validation.ok && !isBuilding && !isPublished;

  const detailRound = selectedRoundId
    ? req.rounds.find((r) => r.id === selectedRoundId)
    : undefined;

  const rememberAsRole = (roleStatus: 'draft' | 'live') => {
    const roleStore = useRoleStore.getState();
    const existing = roleStore.roles.find((r) => r.id === req.id);
    if (existing) {
      roleStore.updateRole(req.id, { status: roleStatus });
      return;
    }
    roleStore.addRole({
      id: req.id,
      title: req.roleTitle,
      loc: req.roleLocation,
      pipeline: `${req.rounds.length} rounds`,
      status: roleStatus,
      dept: 'Unassigned',
      owner: 'Nitin',
      created_at: new Date().toISOString(),
      ready_to_debrief: false,
      must_have: Array.from(new Set(req.rounds.flatMap((r) => r.skills))),
      nice_to_have: [],
    });
  };

  const closeArtifact = () => {
    useSessionStore.getState().setArtifactId('intake', null);
    useArtifactStore.getState().removeArtifact(req.id);
  };

  const handlePublish = async () => {
    const result = publish(req.id);
    if (!result.ok) return;
    rememberAsRole('live');
    useActiveContextStore.getState().setContext({
      requisitionId: req.id,
      roleTitle: req.roleTitle,
      source: 'intake',
    });

    const dashboardId = await mirrorIntakeToDashboard(req, 'planned');

    useSessionStore.getState().appendMessage(
      'intake',
      makeMessage(
        'agent',
        `Published ${req.roleTitle}. Opening it in your roles dashboard.`,
        undefined,
        'scripted',
        [
          ...(dashboardId
            ? [
                {
                  label: 'Open role in dashboard',
                  value: `open_role:${dashboardId}`,
                  primary: true,
                },
              ]
            : []),
          { label: 'Start another role', value: 'start_another' },
        ],
      ),
    );
    setSavedAsDraft(false);
    closeArtifact();
    if (dashboardId) router.push(`/view/roles/${dashboardId}`);
  };

  const handleSaveDraft = async () => {
    rememberAsRole('draft');
    const dashboardId = await mirrorIntakeToDashboard(req, 'intake_pending');

    useSessionStore.getState().appendMessage(
      'intake',
      makeMessage(
        'agent',
        `Saved ${req.roleTitle} as a draft. Opening it in your roles dashboard.`,
        undefined,
        'scripted',
        [
          ...(dashboardId
            ? [
                {
                  label: 'Open role in dashboard',
                  value: `open_role:${dashboardId}`,
                  primary: true,
                },
              ]
            : []),
          { label: 'Publish now', value: 'publish_now' },
        ],
      ),
    );
    setSavedAsDraft(true);
    closeArtifact();
    if (dashboardId) router.push(`/view/roles/${dashboardId}`);
  };

  return (
    <div id={id} className="flex flex-col gap-7 pb-10">
      <section id={`${id}-hero`} className="flex items-start gap-3">
        <div
          id={`${id}-hero-icon`}
          aria-hidden
          className="flex h-10 w-10 items-center justify-center rounded-[12px] bg-surface text-text-primary"
        >
          <Briefcase strokeWidth={1.75} className="h-4 w-4" />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h2
            id={`${id}-hero-title`}
            className="font-display font-normal text-[30px] text-text-primary leading-tight tracking-[-0.01em]"
          >
            {req.roleTitle}
          </h2>
          <p id={`${id}-hero-sub`} className="text-[13.5px] text-text-muted">
            {req.roleLocation} · {experienceDisplay(req.experienceMinYears, req.experienceMaxYears)}
          </p>
          <span
            id={`${id}-hero-status`}
            className={`mt-1 inline-flex w-fit items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10.5px] uppercase tracking-[0.14em] ${
              isPublished
                ? 'bg-[#ECFDF5] text-[#047857]'
                : savedAsDraft
                  ? 'bg-surface text-text-primary'
                  : 'bg-surface text-text-muted'
            }`}
          >
            {isPublished
              ? 'Published · Live'
              : savedAsDraft
                ? 'Saved · Draft'
                : isBuilding
                  ? 'Drafting'
                  : 'Draft'}
          </span>
        </div>
        {!isPublished && !savedAsDraft && (
          <div id={`${id}-hero-actions`} className="flex shrink-0 items-center gap-2">
            <button
              id={`${id}-hero-save`}
              type="button"
              onClick={handleSaveDraft}
              disabled={isBuilding}
              className="inline-flex items-center gap-2 rounded-full border border-border bg-white px-3.5 py-1.5 font-medium font-sans text-[12.5px] text-text-primary transition hover:border-text-primary disabled:cursor-not-allowed disabled:opacity-30"
            >
              Save as draft
            </button>
            <button
              id={`${id}-hero-publish`}
              type="button"
              onClick={handlePublish}
              disabled={!canPublish}
              className="inline-flex items-center gap-2 rounded-full bg-text-primary px-3.5 py-1.5 font-medium font-sans text-[12.5px] text-bg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-30"
            >
              Publish
            </button>
          </div>
        )}
      </section>

      {isBuilding && (
        <section id={`${id}-building`} className="flex flex-col gap-4">
          <div id={`${id}-building-intro`} className="flex flex-col gap-1">
            <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
              Constructing your interview plan
            </span>
            <p className="font-sans text-[13.5px] text-text-primary leading-relaxed">
              Rounds, guidelines, and evaluation criteria will appear below as each one lands.
            </p>
          </div>
          <ul id={`${id}-checklist`} className="flex flex-col gap-2">
            {CHECKLIST.map((item, i) => {
              const completed = currentStageIdx > i;
              const active = currentStageIdx === i;
              return (
                <li
                  key={item.key}
                  id={`${id}-checklist-${item.key}`}
                  className="flex items-center gap-2.5 font-sans text-[13px]"
                >
                  <span
                    aria-hidden
                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${
                      completed
                        ? 'bg-cortex-500 text-white'
                        : active
                          ? 'border border-cortex-500 text-cortex-500'
                          : 'border border-border text-text-muted'
                    }`}
                  >
                    {completed ? (
                      <Check strokeWidth={2.25} className="h-2.5 w-2.5" />
                    ) : active ? (
                      <Loader2 strokeWidth={2.25} className="h-2.5 w-2.5 animate-spin" />
                    ) : null}
                  </span>
                  <span className={completed || active ? 'text-text-primary' : 'text-text-muted'}>
                    {item.label}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {(req.intakeSummary || (isBuilding && currentStageIdx >= 0)) && (
        <section id={`${id}-summary`} className="flex flex-col gap-2">
          <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
            Role summary
          </span>
          {req.intakeSummary ? (
            <RoleSummary id={`${id}-summary-body`} markdown={req.intakeSummary} />
          ) : (
            <SkeletonLines
              id={`${id}-summary-skeleton`}
              lines={4}
              widths={['96%', '88%', '100%', '72%']}
            />
          )}
        </section>
      )}

      {detailRound ? (
        <RoundDetailView
          id={`${id}-detail`}
          reqId={req.id}
          roundId={detailRound.id}
          onBack={() => setSelectedRoundId(null)}
          onNext={(nextId) => setSelectedRoundId(nextId)}
        />
      ) : (
        req.rounds.length > 0 && (
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
                Interview Plan · {req.rounds.length} {req.rounds.length === 1 ? 'round' : 'rounds'}
              </span>
              {req.rounds.some((r) => r.screeningAgentEnabled) && (
                <span
                  id={`${id}-rounds-ai-hint`}
                  className="font-mono text-[10.5px] text-cortex-500 uppercase tracking-[0.14em]"
                >
                  AI-hosted · 1 round
                </span>
              )}
            </div>
            <RoundList
              id={`${id}-rounds`}
              reqId={req.id}
              onSelect={setSelectedRoundId}
              buildingRoundIds={
                isBuilding
                  ? req.rounds.filter((r) => r.feedbackQuestions.length === 0).map((r) => r.id)
                  : []
              }
            />
          </section>
        )
      )}

      {!detailRound && !isBuilding && !isPublished && !savedAsDraft && !canPublish && (
        <footer
          id={`${id}-footer-hint`}
          className="flex flex-wrap items-center gap-2 border-border border-t pt-4"
        >
          <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
            Each round needs ≥1 feedback question before Publish unlocks
          </span>
        </footer>
      )}
    </div>
  );
}
