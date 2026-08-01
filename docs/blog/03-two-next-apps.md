# Packaging two Next.js apps and a shared cookie

> Outline. The full post is a follow-on writing effort.

- Login lives in one app, the dashboard in another; a shared cookie joins them.
- Two invariants that produce an infinite redirect loop when violated: identical
  `@supabase/ssr` version, and the right cookie domain (blank for localhost).
- `NEXT_PUBLIC_*` must be present at BUILD time and RUN time. A blank runtime
  value overrides the baked one, because server components read process.env per
  request.
- Tailwind v4: a utility whose token is missing from `@theme` emits no CSS and
  fails silently. Renaming a design token means moving the declaration, the
  alias, every var(), and the test that guards it.
- Three voice-URL resolvers picked a backend by matching a vendor hostname.
  Substituting the domain produced a branch testing a hostname for a port --
  which a hostname never contains. Dead code that looked fine.
- The de-brand grep never sees filenames.
