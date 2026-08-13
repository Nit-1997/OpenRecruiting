# Supabase setup

OpenRecruiting uses a **cloud Supabase project** for its database and auth. Supabase is
the one dependency that does not run in `docker compose` — you bring your own project.
The free tier is enough.

Budget about ten minutes.

## 1. Create the project

Create a project at <https://supabase.com>. Pick a region near you and save the database
password somewhere — you will not be shown it again (you do not need it for the steps
below, only for direct `psql` access).

## 2. Apply the schema

Open **SQL Editor → New query**, paste the entire contents of [`schema.sql`](../schema.sql),
and press **Run**.

This is one consolidated file — the project's whole history of migrations squashed into a
single script. It should finish with **no errors**.

It runs as **one transaction**, so it either lands completely or changes nothing. If the
SQL editor times out part-way through, the database is left untouched and you can simply
run it again.

It also **refuses to run twice**. A second attempt stops immediately with:

```
OpenRecruiting schema is already applied to this database. Nothing was changed.
```

That is the file protecting you, not an error to work around. It is not a migration
runner and does not track versions — it is for a fresh project.

The `REVOKE EXECUTE ... FROM authenticated, PUBLIC` lines near the end are not noise —
they are what stops the `SECURITY DEFINER` functions from being callable by ordinary
logged-in users. Do not strip them.

**Optional demo data:** paste [`seed.sql`](../seed.sql) into a new query and run it.
It adds one organization, a requisition with two rounds, two candidates and a transcript.
Read the note at the bottom of that file — you must attach your account to the demo
organization after signing up, or row-level security will (correctly) hide all of it.

## 3. Enter your keys

Open the setup UI at **<http://127.0.0.1:3010>** and fill in the first four
fields under **Get started**:

| Setup UI field | Where to find it in Supabase |
|---|---|
| Supabase project URL | Project Settings → API keys → Project URL |
| Supabase publishable key | Project Settings → API keys → `anon` / publishable |
| Supabase secret key | Project Settings → API keys → `service_role` / secret |
| Supabase JWT secret | Project Settings → API → JWT Settings → JWT Secret |

Press **Review & apply**. The UI writes them and recreates only the services that
read them.

> **One field per real decision.** The project URL and the publishable key each
> live under *two* variable names, because the backend and the browser read
> different ones. The setup UI writes both copies from the single value you
> entered — that duplication used to be yours to keep in sync, and drift between
> the copies is a failure this project has already shipped.

Three of those four have no default: the backend refuses to start without the
project URL, the secret key, or the JWT secret.

**Why the publishable key has two names.** Supabase renamed it — newer projects
say "publishable", older ones say "anon". Same string. It is publishable by
design and safe in a browser.

**The secret key bypasses row-level security entirely.** It belongs to the
backend alone. The setup UI treats it as write-only and never returns it to the
page; if you ever set it by hand, never put it in a `NEXT_PUBLIC_*` variable —
those are compiled into the browser bundle.

**The JWT secret is required, but not for the reason its name suggests.** This
project's Supabase issues **ES256** access tokens, which the backend verifies
against your project's public JWKS — the shared secret plays no part in checking
a user login. It signs the backend's *own* HS256 tokens: screening sessions, OTP
codes and public feedback links. Any long random string works if you would rather
not reuse the dashboard's value.

## 4. Configure auth URLs

Under **Authentication → URL Configuration**:

- **Site URL:** `http://localhost:3000`
- **Redirect URLs:** add `http://localhost:3000/**` and `http://localhost:3005/**`, plus
  your public hostname once you have one — `https://app.example.com/**`

Then under **Authentication → Sign In / Providers**, make sure **Email** is enabled.
Password sign-in works out of the box.

Google sign-in is optional and configured separately — see
[Google sign-in](google-auth.md).

If you skip this step, login appears to succeed and then bounces you back to the login
page — the redirect is rejected by Supabase, not by the app.

## 5. Create your first recruiter

Sign up through the landing app at `http://localhost:3000` once the stack is running.
The backend creates your profile on first login.

Self-hosted instances are not invite-gated by default. To close signup on a
shared deployment, turn on **Advanced → Invite-only signup** in the setup UI.

To make yourself a staff user, run this in the SQL editor after signing up:

```sql
UPDATE public.profiles SET is_staff = true WHERE email = 'you@example.com';
```

## 6. Staff access to the admin portal

`admin-app` on <http://localhost:3001> is the staff console — organizations and
their credit budgets, requisitions, and the blog. It is gated entirely on
`profiles.is_staff`, which is effectively superuser across every organization in
the instance. Do not set it on ordinary recruiter accounts.

To create a staff account in one step, edit the CONFIG block at the top of
[`staff_user.sql`](../staff_user.sql) and run it in the SQL editor. It
provisions the Supabase Auth user, the confirmed email identity and the staff
profile together, and is safe to re-run (it resets the password rather than
creating a duplicate).

That script also carries one grant your database may be missing:

```sql
GRANT EXECUTE ON FUNCTION public.is_admin() TO authenticated;
```

`is_admin()` is not an RPC — 39 row-level-security policies across 15 tables
call it, and a policy predicate runs with the *caller's* privileges. Without the
grant, every authenticated client-side read of those tables fails with
`permission denied for function is_admin` and the admin portal cannot confirm
you are staff. `schema.sql` now includes it; databases created before that fix
need `staff_user.sql` (or the statement above) once.

## Troubleshooting

**"relation does not exist" when the app loads.** `schema.sql` never completed. Because it
runs in one transaction, a failure rolled the whole thing back — so nothing was half-built.
Read the error the SQL editor reported, fix the cause, and run the file once more.

**"schema is already applied".** The guard at the top of the file found the `organizations`
table, so it stopped without changing anything. If you genuinely want to start over, delete
the project's data first; do not try to force the file through.

**Login loops back to the login page.** Step 4 — the redirect URLs are missing.

**Logged in, but every list is empty.** Expected on a fresh instance: row-level security
scopes all data to your profile's organization. Either create a requisition through the
app, or run the ATTACH statement at the bottom of `seed.sql`.

**`permission denied for schema public` while running `schema.sql`.** You are running as
something other than the project owner. Use the dashboard SQL editor rather than an
external client.
