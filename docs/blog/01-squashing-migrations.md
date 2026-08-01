# Squashing 133 migrations into one schema

> Outline. The full post is a follow-on writing effort.

- The goal: `git clone` -> paste one file into the Supabase SQL editor -> done.
- Generate, don't hand-write: replay every migration against a clean Postgres and
  dump the result. The database is the source of truth about the database.
- The migrations did not replay under `ON_ERROR_STOP`, and the reason is a good
  Postgres gotcha: `DROP TRIGGER IF EXISTS x ON tbl` still errors when *tbl*
  doesn't exist. IF EXISTS guards the trigger, not the relation.
- Proving a messy replay was nonetheless complete: map every error back to the
  statement that produced it and show they are all drop-guards.
- The landmine: renaming a staff-flag column to `is_staff` inside a function that
  already declared a local variable called `is_staff`. `SELECT is_staff INTO
  is_staff` raises "column reference is ambiguous" -- at RUNTIME, not at
  definition time. It would have silently broken every admin RLS check.
- Why `pg_dump --no-privileges` would have been a security bug here.
