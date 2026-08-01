'use client';

import { Skeleton, SkeletonLines } from '@/components/shell/primitives/skeleton';

interface BaseProps {
  id: string;
}

// Roles list table card: column header + N row placeholders. The page header,
// tabs and search above it render for real (no data dependency), so this only
// fills the table region — zero shift when rows land.
export function RolesTableSkeleton({ id, rows = 6 }: BaseProps & { rows?: number }) {
  return (
    <div id={id} className="divide-y divide-border rounded-[14px] border border-border bg-white">
      <div id={`${id}-head`} className="flex items-center gap-3 bg-surface px-4 py-2.5">
        <Skeleton id={`${id}-head-a`} className="h-2.5 w-16" rounded="sm" />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder list
          key={i}
          id={`${id}-row-${i}`}
          className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)_36px] items-center gap-3 px-4 py-3.5"
        >
          <div className="flex flex-col gap-1.5">
            <Skeleton id={`${id}-row-${i}-title`} className="h-3.5 w-48" rounded="sm" />
            <Skeleton id={`${id}-row-${i}-sub`} className="h-2.5 w-28" rounded="sm" />
          </div>
          <Skeleton id={`${id}-row-${i}-dept`} className="h-3 w-20" rounded="sm" />
          <Skeleton id={`${id}-row-${i}-owner`} className="h-3 w-24" rounded="sm" />
          <Skeleton id={`${id}-row-${i}-pipe`} className="h-3 w-32" rounded="sm" />
          <Skeleton id={`${id}-row-${i}-kebab`} className="h-5 w-5" rounded="pill" />
        </div>
      ))}
    </div>
  );
}

// Pipeline tab: a vertical stack of candidate-row cards.
export function PipelineSkeleton({ id, rows = 4 }: BaseProps & { rows?: number }) {
  return (
    <div id={id} className="flex flex-col gap-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder list
          key={i}
          id={`${id}-row-${i}`}
          className="rounded-[14px] border border-border bg-white p-4"
        >
          <div className="mb-3 flex items-center gap-3">
            <Skeleton id={`${id}-row-${i}-av`} className="h-9 w-9" rounded="pill" />
            <div className="flex flex-col gap-1.5">
              <Skeleton id={`${id}-row-${i}-name`} className="h-3.5 w-40" rounded="sm" />
              <Skeleton id={`${id}-row-${i}-meta`} className="h-2.5 w-24" rounded="sm" />
            </div>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {Array.from({ length: 4 }).map((__, j) => (
              <Skeleton
                // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder list
                key={j}
                id={`${id}-row-${i}-cell-${j}`}
                className="h-12 w-full"
                rounded="md"
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// Role detail page: back pill + title/meta header + tablist + pipeline rows.
export function RoleDetailSkeleton({ id }: BaseProps) {
  return (
    <div id={id} className="pt-6 pb-8 sm:pt-10">
      <Skeleton id={`${id}-back`} className="mb-4 h-7 w-24" rounded="pill" />
      <div id={`${id}-header`} className="mb-6 border-border border-b pb-5">
        <Skeleton id={`${id}-title`} className="h-9 w-80 max-w-full" rounded="md" />
        <div className="mt-3 flex gap-3">
          <Skeleton id={`${id}-meta-a`} className="h-3 w-28" rounded="sm" />
          <Skeleton id={`${id}-meta-b`} className="h-3 w-24" rounded="sm" />
        </div>
      </div>
      <Skeleton id={`${id}-tabs`} className="mb-6 h-10 w-full" rounded="lg" />
      <PipelineSkeleton id={`${id}-pipeline`} rows={3} />
    </div>
  );
}

// Packet drawer right pane: stat grid + summary + criteria blocks.
export function PacketPaneSkeleton({ id }: BaseProps) {
  return (
    <div id={id} className="flex flex-col gap-4">
      <div id={`${id}-stats`} className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton
            // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder list
            key={i}
            id={`${id}-stat-${i}`}
            className="h-16 w-full"
            rounded="md"
          />
        ))}
      </div>
      <Skeleton id={`${id}-summary`} className="h-24 w-full" rounded="lg" />
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder list
          key={i}
          id={`${id}-q-${i}`}
          className="rounded-[12px] border border-border bg-white p-4"
        >
          <Skeleton id={`${id}-q-${i}-h`} className="mb-3 h-3.5 w-56 max-w-full" rounded="sm" />
          <SkeletonLines id={`${id}-q-${i}-body`} lines={2} />
        </div>
      ))}
    </div>
  );
}

// Settings card (Team / Billing): section header + bordered card rows.
export function SettingsCardSkeleton({ id, rows = 3 }: BaseProps & { rows?: number }) {
  return (
    <div id={id} className="flex flex-col gap-4">
      <Skeleton id={`${id}-h`} className="h-5 w-40" rounded="sm" />
      <div id={`${id}-card`} className="divide-y divide-border rounded-[12px] border border-border">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder list
            key={i}
            id={`${id}-row-${i}`}
            className="flex items-center gap-3 px-4 py-3"
          >
            <Skeleton id={`${id}-row-${i}-av`} className="h-8 w-8" rounded="pill" />
            <Skeleton id={`${id}-row-${i}-line`} className="h-3.5 w-48 max-w-full" rounded="sm" />
          </div>
        ))}
      </div>
    </div>
  );
}

// Intake hub: bento hero + two preview cards.
export function IntakeHubSkeleton({ id }: BaseProps) {
  return (
    <div id={id} className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <Skeleton id={`${id}-hero`} className="h-72 w-full" rounded="lg" />
      <div className="flex flex-col gap-4">
        <Skeleton id={`${id}-card-1`} className="h-[136px] w-full" rounded="lg" />
        <Skeleton id={`${id}-card-2`} className="h-[136px] w-full" rounded="lg" />
      </div>
    </div>
  );
}
