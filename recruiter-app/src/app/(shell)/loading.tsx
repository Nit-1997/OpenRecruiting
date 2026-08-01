import { Skeleton, SkeletonLines } from '@/components/shell/primitives/skeleton';

/**
 * Shell-scoped loading UI (Next.js 16 `loading.tsx` convention).
 *
 * Wraps shell pages in a `<Suspense>` fallback — covers the async
 * `sessions/[id]` server route (which has no closer `loading.tsx`) and any
 * other shell server segment, so navigation shows a branded skeleton instead
 * of blocking on a white screen. Reuses the existing skeleton primitive.
 */
export default function ShellLoading() {
  return (
    <div
      id="shell-loading-root"
      role="status"
      aria-busy="true"
      aria-label="Loading"
      className="flex h-full flex-col gap-6 px-6 py-8"
    >
      <Skeleton id="shell-loading-title" className="h-7 w-56" rounded="md" />
      <div id="shell-loading-body" className="flex flex-col gap-4">
        <SkeletonLines id="shell-loading-lines-1" lines={4} />
        <SkeletonLines id="shell-loading-lines-2" lines={3} widths={['88%', '70%', '52%']} />
      </div>
      <span id="shell-loading-sr" className="sr-only">
        Loading content
      </span>
    </div>
  );
}
