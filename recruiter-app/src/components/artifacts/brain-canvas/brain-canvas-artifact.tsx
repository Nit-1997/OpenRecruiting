'use client';

import { AlertTriangle, Search, Sparkles, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import type {
  BrainLink,
  BrainNode,
  BrainNodeType,
  BrainStory,
  BrainStorySeverity,
  BrainTimeRangeId,
} from '@/fixtures/brain';
import { BRAIN_TIME_RANGES } from '@/fixtures/brain';
import { cn } from '@/lib/utils';
import { useTypedArtifact } from '../_shared/use-artifact-data';
import { ForceGraph } from './force-graph';

type NodeFilter = 'all' | BrainNodeType;

const NODE_FILTERS: Array<{ id: NodeFilter; label: string; dot?: string }> = [
  { id: 'all', label: 'All' },
  { id: 'role', label: 'Roles', dot: '#7A6BD9' },
  { id: 'interviewer', label: 'Interviewers', dot: '#555555' },
  { id: 'signal', label: 'Signals', dot: '#B45309' },
];

export interface BrainCanvasArtifactData {
  weekLabel: string;
  timeRangeId: BrainTimeRangeId;
  nodes: BrainNode[];
  links: BrainLink[];
  stories: BrainStory[];
  mutedStoryIds: string[];
  focusedNodeId: string | null;
  highlightedNodeIds: string[];
  activeStoryId: string | null;
}

interface BrainCanvasArtifactProps {
  id: string;
  artifactId: string;
  onStoryExplain?: (storyId: string) => void;
  onStoryMute?: (storyId: string) => void;
  onNodeFocus?: (nodeId: string) => void;
  onRangeChange?: (rangeId: BrainTimeRangeId) => void;
  onClearFocus?: () => void;
  onSearch?: (query: string) => void;
  onFilterType?: (type: BrainNodeType | null) => void;
}

const SEVERITY_DOT_COLOR: Record<BrainStorySeverity, string> = {
  info: 'bg-[#1D4ED8]',
  warn: 'bg-[#B45309]',
  danger: 'bg-[#DC2626]',
};

const SEVERITY_LABEL: Record<BrainStorySeverity, string> = {
  info: 'Info',
  warn: 'Watch',
  danger: 'Urgent',
};

export function BrainCanvasArtifact({
  id,
  artifactId,
  onStoryExplain,
  onStoryMute,
  onNodeFocus,
  onRangeChange,
  onClearFocus,
  onSearch,
  onFilterType,
}: BrainCanvasArtifactProps) {
  const artifact = useTypedArtifact(artifactId, 'brain-canvas');
  const rawData = artifact?.data ?? null;
  const [activeFilter, setActiveFilter] = useState<NodeFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const handleFilter = (filter: NodeFilter) => {
    setActiveFilter(filter);
    setSearchQuery('');
    onFilterType?.(filter === 'all' ? null : filter);
  };

  const handleSearchChange = (q: string) => {
    setSearchQuery(q);
    setActiveFilter('all');
    onSearch?.(q);
  };

  const muted = useMemo(() => new Set(rawData?.mutedStoryIds ?? []), [rawData?.mutedStoryIds]);
  const stories = useMemo(
    () => (rawData?.stories ?? []).filter((s) => !muted.has(s.id)),
    [rawData?.stories, muted],
  );
  const activeStory = useMemo(
    () => stories.find((s) => s.id === rawData?.activeStoryId) ?? null,
    [stories, rawData?.activeStoryId],
  );
  const activeNode = useMemo(() => {
    if (!rawData?.focusedNodeId) return null;
    return (rawData.nodes ?? []).find((n) => n.id === rawData.focusedNodeId) ?? null;
  }, [rawData?.focusedNodeId, rawData?.nodes]);

  if (!artifact || !rawData?.nodes || !rawData.links || !rawData.stories) return null;

  const data = rawData;
  const nodeCount = data.nodes.length;
  const linkCount = data.links.length;

  return (
    <section
      id={id}
      aria-busy={artifact.isBuilding ?? false}
      aria-label="Brain canvas artifact"
      className="flex min-w-0 flex-col"
    >
      <header
        id={`${id}-head`}
        className="mb-4 flex flex-wrap items-end justify-between gap-3 border-border border-b pb-3"
      >
        <div id={`${id}-head-left`} className="min-w-0">
          <div
            id={`${id}-eyebrow`}
            className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
          >
            OpenRecruiting Brain · Knowledge graph
          </div>
          <h2
            id={`${id}-headline`}
            className="mt-1 font-display text-[22px] text-text-primary leading-tight tracking-[-0.005em]"
          >
            OpenRecruiting Brain <span className="text-text-muted">· {data.weekLabel}</span>
          </h2>
          <div
            id={`${id}-stats`}
            className="mt-1 flex items-center gap-4 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
          >
            <span id={`${id}-stat-nodes`}>{nodeCount} entities</span>
            <span id={`${id}-stat-links`}>{linkCount} relationships</span>
            <span id={`${id}-stat-stories`}>
              {stories.length} {stories.length === 1 ? 'story' : 'stories'}
            </span>
          </div>
        </div>
        <div id={`${id}-range`} className="flex flex-wrap items-center gap-1.5">
          {BRAIN_TIME_RANGES.map((r) => {
            const active = data.timeRangeId === r.id;
            return (
              <button
                key={r.id}
                id={`${id}-range-${r.id}`}
                type="button"
                onClick={() => onRangeChange?.(r.id)}
                className={cn(
                  'inline-flex items-center rounded-full border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.14em] transition-colors',
                  active
                    ? 'border-text-primary bg-text-primary text-white'
                    : 'border-border bg-white text-text-muted hover:border-text-primary hover:text-text-primary',
                )}
              >
                {r.label}
              </button>
            );
          })}
        </div>
      </header>

      <div
        id={`${id}-graph-wrap`}
        className="relative mb-4 rounded-[14px] border border-border bg-surface-accent/40"
      >
        <div
          id={`${id}-graph-toolbar`}
          className="flex flex-wrap items-center gap-2 border-border/60 border-b px-3 py-2.5"
        >
          <div id={`${id}-graph-filters`} className="flex flex-wrap items-center gap-1">
            {NODE_FILTERS.map((f) => {
              const active = activeFilter === f.id;
              return (
                <button
                  key={f.id}
                  id={`${id}-graph-filter-${f.id}`}
                  type="button"
                  onClick={() => handleFilter(f.id)}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium font-sans text-[11px] transition-colors',
                    active
                      ? 'border-text-primary bg-text-primary text-white'
                      : 'border-border bg-white text-text-muted hover:border-text-primary hover:text-text-primary',
                  )}
                >
                  {f.dot && (
                    <span
                      aria-hidden
                      className="h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{ background: f.dot }}
                    />
                  )}
                  {f.label}
                </button>
              );
            })}
          </div>
          <div
            id={`${id}-graph-search`}
            className="ml-auto flex min-w-[180px] flex-1 items-center gap-1.5 rounded-full border border-border bg-white px-2.5 py-1 transition-colors focus-within:border-text-primary md:max-w-[260px]"
          >
            <Search aria-hidden strokeWidth={1.75} className="h-3.5 w-3.5 text-text-muted" />
            <input
              id={`${id}-graph-search-input`}
              type="text"
              value={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Search nodes…"
              aria-label="Search graph nodes"
              className="min-w-0 flex-1 border-0 bg-transparent text-[12px] text-text-primary placeholder:text-text-muted focus:outline-none"
            />
            {searchQuery && (
              <button
                id={`${id}-graph-search-clear`}
                type="button"
                aria-label="Clear search"
                onClick={() => handleSearchChange('')}
                className="flex h-4 w-4 items-center justify-center rounded-full text-text-muted hover:text-text-primary"
              >
                <X strokeWidth={1.75} className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
        <div id={`${id}-graph`} className="h-[380px] w-full px-2 pb-2 pt-1">
          <ForceGraph
            id={`${id}-graph-svg`}
            nodes={data.nodes}
            links={data.links}
            focusedNodeId={data.focusedNodeId}
            highlightedNodeIds={data.highlightedNodeIds}
            onNodeClick={(node) => onNodeFocus?.(node.id)}
            onBackgroundClick={() => {
              setActiveFilter('all');
              setSearchQuery('');
              onClearFocus?.();
            }}
          />
        </div>
        {activeNode && (
          <button
            id={`${id}-clear-focus`}
            type="button"
            onClick={() => onClearFocus?.()}
            className="absolute top-[58px] right-3 inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-3 py-1 font-mono text-[10px] text-text-muted uppercase tracking-[0.14em] transition-colors hover:border-text-primary hover:text-text-primary"
          >
            <X strokeWidth={1.75} className="h-3 w-3" />
            Clear focus
          </button>
        )}
      </div>

      <section id={`${id}-stories`} aria-label="Brain stories" className="flex flex-col gap-2.5">
        <div
          id={`${id}-stories-eyebrow`}
          className="flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
        >
          <Sparkles strokeWidth={1.75} className="h-3 w-3" />
          Stories OpenRecruiting is tracking
        </div>
        {stories.length === 0 && (
          <div
            id={`${id}-stories-empty`}
            className="rounded-[14px] border border-border border-dashed bg-white px-5 py-8 text-center text-[13px] text-text-muted"
          >
            All stories muted. Toggle a range above to load new signals.
          </div>
        )}
        <div id={`${id}-stories-list`} className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
          {stories.map((s) => (
            <StoryCard
              key={s.id}
              id={`${id}-story-${s.id}`}
              story={s}
              active={activeStory?.id === s.id}
              onExplain={onStoryExplain ?? (() => {})}
              onMute={onStoryMute ?? (() => {})}
            />
          ))}
        </div>
      </section>

      {(activeStory || activeNode) && (
        <section
          id={`${id}-drilldown`}
          aria-label="Drill-down panel"
          className="mt-4 rounded-[14px] border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm p-4"
        >
          {activeStory ? (
            <StoryDrilldown id={`${id}-drilldown-story`} story={activeStory} />
          ) : activeNode ? (
            <NodeDrilldown
              id={`${id}-drilldown-node`}
              node={activeNode}
              relatedStories={stories.filter((s) => s.targetIds.includes(activeNode.id))}
              links={data.links}
              allNodes={data.nodes}
            />
          ) : null}
        </section>
      )}
    </section>
  );
}

interface StoryCardProps {
  id: string;
  story: BrainStory;
  active: boolean;
  onExplain: (storyId: string) => void;
  onMute: (storyId: string) => void;
}

function StoryCard({ id, story, active, onExplain, onMute }: StoryCardProps) {
  return (
    <article
      id={id}
      className={cn(
        'flex flex-col gap-2 rounded-[12px] border bg-white p-3.5 transition-colors',
        active ? 'border-text-primary' : 'border-border hover:border-text-primary',
      )}
    >
      <header id={`${id}-head`} className="flex items-start gap-2">
        <span
          id={`${id}-dot`}
          aria-hidden
          className={cn('mt-1 h-2 w-2 shrink-0 rounded-full', SEVERITY_DOT_COLOR[story.severity])}
        />
        <div id={`${id}-head-text`} className="min-w-0 flex-1">
          <div
            id={`${id}-sev`}
            className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.18em]"
          >
            {SEVERITY_LABEL[story.severity]}
          </div>
          <h3
            id={`${id}-title`}
            className="mt-0.5 font-medium font-sans text-[13.5px] text-text-primary leading-[1.3]"
          >
            {story.title}
          </h3>
        </div>
      </header>
      <p id={`${id}-body`} className="text-[12.5px] text-text-secondary leading-[1.5]">
        {story.body}
      </p>
      <footer id={`${id}-actions`} className="mt-1 flex items-center justify-between gap-2">
        <button
          id={`${id}-explain`}
          type="button"
          onClick={() => onExplain(story.id)}
          className="inline-flex items-center gap-1 rounded-full border border-text-primary bg-text-primary px-2.5 py-1 font-medium font-sans text-[11.5px] text-white transition-colors hover:bg-[#222]"
        >
          <AlertTriangle strokeWidth={1.75} className="h-3 w-3" />
          Explain
        </button>
        <button
          id={`${id}-mute`}
          type="button"
          onClick={() => onMute(story.id)}
          className="inline-flex items-center gap-1 rounded-full border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-2.5 py-1 font-medium font-sans text-[11.5px] text-text-muted transition-colors hover:border-text-primary hover:text-text-primary"
        >
          Mute
        </button>
      </footer>
    </article>
  );
}

function StoryDrilldown({ id, story }: { id: string; story: BrainStory }) {
  return (
    <div id={id} className="flex flex-col gap-2.5">
      <div
        id={`${id}-eyebrow`}
        className="flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
      >
        <span
          id={`${id}-dot`}
          aria-hidden
          className={cn('h-2 w-2 rounded-full', SEVERITY_DOT_COLOR[story.severity])}
        />
        {SEVERITY_LABEL[story.severity]} · Drill-down
      </div>
      <h3
        id={`${id}-title`}
        className="font-display text-[18px] text-text-primary leading-tight tracking-[-0.005em]"
      >
        {story.title}
      </h3>
      <p id={`${id}-body`} className="text-[13px] text-text-secondary leading-[1.55]">
        {story.elaboration}
      </p>
      {story.evidence.length > 0 && (
        <ul id={`${id}-evidence`} className="mt-1 flex flex-col gap-1">
          {story.evidence.map((e, idx) => (
            <li
              // biome-ignore lint/suspicious/noArrayIndexKey: evidence strings are static per story
              key={idx}
              id={`${id}-evidence-${idx}`}
              className="rounded-[8px] bg-surface px-2.5 py-1.5 font-mono text-[11px] text-text-secondary"
            >
              {e}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function NodeDrilldown({
  id,
  node,
  relatedStories,
  links,
  allNodes,
}: {
  id: string;
  node: BrainNode;
  relatedStories: BrainStory[];
  links: BrainLink[];
  allNodes: BrainNode[];
}) {
  const neighbors = useMemo(() => {
    const ids = new Set<string>();
    for (const l of links) {
      if (l.source === node.id) ids.add(l.target);
      if (l.target === node.id) ids.add(l.source);
    }
    return allNodes.filter((n) => ids.has(n.id));
  }, [links, node.id, allNodes]);

  return (
    <div id={id} className="flex flex-col gap-2.5">
      <div
        id={`${id}-eyebrow`}
        className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
      >
        Node · {node.type}
      </div>
      <h3
        id={`${id}-title`}
        className="font-display text-[18px] text-text-primary leading-tight tracking-[-0.005em]"
      >
        {node.label}
      </h3>
      <p id={`${id}-meta`} className="text-[13px] text-text-muted leading-[1.55]">
        {node.meta} · {neighbors.length} {neighbors.length === 1 ? 'connection' : 'connections'}
      </p>
      {relatedStories.length > 0 && (
        <div id={`${id}-stories`} className="mt-1 flex flex-col gap-1.5">
          <div
            id={`${id}-stories-label`}
            className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
          >
            Related stories
          </div>
          {relatedStories.map((s) => (
            <div
              key={s.id}
              id={`${id}-story-${s.id}`}
              className="rounded-[8px] border border-border bg-surface px-2.5 py-1.5 text-[11.5px] text-text-secondary"
            >
              {s.title}
            </div>
          ))}
        </div>
      )}
      {neighbors.length > 0 && (
        <div id={`${id}-neighbors`} className="mt-1 flex flex-wrap gap-1.5">
          {neighbors.map((n) => (
            <span
              key={n.id}
              id={`${id}-neighbor-${n.id}`}
              className="inline-flex items-center rounded-full border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-2.5 py-1 font-mono text-[10.5px] text-text-secondary uppercase tracking-[0.14em]"
            >
              {n.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
