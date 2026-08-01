import Link from 'next/link';

/**
 * Root 404 page (Next.js 16 `not-found.tsx` convention).
 *
 * Renders for unmatched URLs across the whole app and for any `notFound()`
 * thrown in a segment without a closer `not-found.tsx`. This is a Server
 * Component and accepts no props.
 */
export default function NotFound() {
  return (
    <main
      id="app-not-found-root"
      className="flex min-h-screen flex-col items-center justify-center gap-5 bg-canvas px-6 text-center"
    >
      <span
        id="app-not-found-mark"
        aria-hidden
        className="font-serif text-2xl italic text-[var(--color-accent-agent)]"
      >
        OpenRecruiting
      </span>
      <h1 id="app-not-found-heading" className="font-serif text-5xl text-text-primary">
        404
      </h1>
      <p id="app-not-found-message" className="max-w-md text-sm text-text-secondary">
        We couldn&apos;t find the page you were looking for. It may have moved or no longer exists.
      </p>
      <Link
        id="app-not-found-home-link"
        href="/"
        className="inline-flex h-9 items-center justify-center rounded-full bg-charcoal px-4 text-[13px] font-medium text-canvas transition-colors hover:bg-charcoal/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/15 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
      >
        Back to home
      </Link>
    </main>
  );
}
