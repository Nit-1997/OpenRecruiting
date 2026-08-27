'use client';

import { useRef } from 'react';
import { useFocusTrap } from '@/hooks/use-focus-trap';
import {
  useArtifactStore,
  useRequisitionStore,
  useRoleStore,
  useSessionStore,
  useShellStore,
} from '@/stores';
import { ArtifactHead } from './artifact-head';
import { ArtifactRenderer } from './artifact-renderer';
import { type WorkspaceTabDescriptor, WorkspaceTabs } from './workspace-tabs';

interface ArtifactColumnProps {
  id: string;
}

export function ArtifactColumn({ id }: ArtifactColumnProps) {
  const activeTabId = useShellStore((s) => s.activeTabId);
  const session = useSessionStore((s) => (activeTabId ? s.sessions[activeTabId] : null));
  const artifactId = session?.artifactId ?? null;
  const artifact = useArtifactStore((s) => (artifactId ? s.artifacts[artifactId] : null));
  const collapse = useArtifactStore((s) => s.collapseArtifact);
  const expand = useArtifactStore((s) => s.expandArtifact);
  const setArtifactId = useSessionStore((s) => s.setArtifactId);

  // FE-J8: the fullscreen artifact dialog is a modal — trap Tab/Shift-Tab and
  // wire Escape through the shared, accessibility-hardened useFocusTrap hook
  // (FE-F2) instead of a bespoke keydown handler that re-scanned the DOM and
  // could land focus on hidden/inert nodes.
  const fullscreenRef = useRef<HTMLDivElement | null>(null);
  const isExpanded = artifact?.expanded === 'expanded';
  useFocusTrap(fullscreenRef, isExpanded, () => {
    if (artifact) collapse(artifact.id);
  });

  if (!activeTabId || !artifact) {
    return (
      <section
        id={id}
        aria-label="Workspace"
        className="flex min-h-0 min-w-0 items-center justify-center border-border border-t bg-white md:border-t-0 md:border-l"
      >
        <div id={`${id}-empty`} className="flex flex-col items-center gap-2 text-center">
          <span className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-text-faint">
            Workspace
          </span>
          <span className="text-[15px] text-text-muted">Nothing open yet.</span>
        </div>
      </section>
    );
  }

  const handleClose = () => {
    if (artifact.type === 'requisition' && artifact.status === 'draft') {
      const roleStore = useRoleStore.getState();
      const req = useRequisitionStore.getState().requisitions[artifact.id];
      if (req && !roleStore.roles.some((r) => r.id === artifact.id)) {
        roleStore.addRole({
          id: artifact.id,
          title: req.roleTitle,
          loc: req.roleLocation || 'Draft',
          pipeline: `${req.rounds.length} rounds`,
          status: 'draft',
          dept: 'Unassigned',
          owner: 'Taylor',
          created_at: new Date().toISOString(),
          ready_to_debrief: false,
          must_have: Array.from(new Set(req.rounds.flatMap((r) => r.skills))),
          nice_to_have: [],
        });
      }
    }
    setArtifactId(activeTabId, null);
  };

  const toggleExpand = () => {
    if (artifact.expanded === 'expanded') collapse(artifact.id);
    else expand(artifact.id);
  };

  // Requisition Publish/Save now lives inside RequisitionArtifact itself —
  // the head has no primary action for this type.
  const requisitionPublish = undefined;

  const isFullscreen = artifact.expanded === 'expanded';
  const history = session?.artifactHistory ?? [];
  const hasBack = history.length > 0;
  const popArtifact = useSessionStore.getState().popArtifact;
  const goBack = hasBack ? () => popArtifact(activeTabId) : undefined;

  const head = (
    <ArtifactHead
      id={`${id}-head`}
      {...(requisitionPublish ? { primaryAction: requisitionPublish } : {})}
      {...(goBack ? { onBack: goBack } : {})}
      expanded={isFullscreen}
      onToggleExpand={toggleExpand}
      onClose={handleClose}
    />
  );

  const workspaceTabs =
    (session?.selections as { workspaceTabs?: WorkspaceTabDescriptor[] } | undefined)
      ?.workspaceTabs ?? [];
  const showTabs = workspaceTabs.length > 0 && !isFullscreen;

  const content = (
    <div id={`${id}-body`} className="scrollable relative flex-1 bg-white">
      <div
        id={`${id}-topbar`}
        className="sticky top-0 z-10 flex items-center justify-between gap-3 border-border/60 border-b bg-white/95 px-4 py-2 backdrop-blur"
      >
        <div id={`${id}-tabs-wrap`} className="min-w-0 flex-1">
          {showTabs ? (
            <WorkspaceTabs
              id={`${id}-tabs`}
              tabs={workspaceTabs}
              activeId={artifact.id}
              onSelect={(tabId) => setArtifactId(activeTabId, tabId)}
            />
          ) : null}
        </div>
        <div className="shrink-0">{head}</div>
      </div>
      <div id={`${id}-content-wrap`} className="px-4 pt-3 pb-8 sm:px-8">
        <ArtifactRenderer
          id={`${id}-content`}
          artifact={artifact}
          selections={session?.selections ?? {}}
        />
      </div>
    </div>
  );

  if (isFullscreen) {
    return (
      <div
        id={`${id}-fullscreen`}
        ref={fullscreenRef}
        role="dialog"
        aria-modal="true"
        aria-label={artifact.title}
        className="fixed inset-0 top-[56px] z-[80] flex items-start justify-center bg-black/40 p-2 sm:p-6"
      >
        <button
          id={`${id}-scrim`}
          type="button"
          aria-label="Close fullscreen"
          onClick={() => collapse(artifact.id)}
          className="absolute inset-0 cursor-default"
        />
        <section
          id={`${id}-fullscreen-surface`}
          className="relative z-10 flex max-h-[calc(100vh-80px)] w-full max-w-[960px] flex-col overflow-hidden rounded-[18px] bg-white shadow-[0_24px_60px_rgba(0,0,0,0.25)]"
        >
          {content}
        </section>
      </div>
    );
  }

  return (
    <section
      id={id}
      aria-label="Workspace"
      className="flex min-h-0 min-w-0 flex-col border-border border-t bg-white md:border-t-0 md:border-l"
    >
      {content}
    </section>
  );
}
