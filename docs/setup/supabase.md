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

Open **SQL Editor → New query**, paste the entire contents of [`schema.sql`](../../schema.sql),
and press **Run**.

This is one consolidated file — the project's whole history of migrations squashed into a
single idempotent script. It creates 53 tables, 178 functions, 89 row-level-security
policies, 222 indexes and 25 triggers, and enables RLS on 50 tables. It should finish
with **no errors**. It is safe to run on a fresh project only; it is not a migration
runner and does not track versions.

The `REVOKE EXECUTE ... FROM authenticated, PUBLIC` lines near the end are not noise —
they are what stops the `SECURITY DEFINER` functions from being callable by ordinary
logged-in users. Do not strip them.

**Optional demo data:** paste [`seed.sql`](../../seed.sql) into a new query and run it.
It adds one organization, a requisition with two rounds, two candidates and a transcript.
Read the note at the bottom of that file — you must attach your account to the demo
organization after signing up, or row-level security will (correctly) hide all of it.

## 3. Copy your keys into `.env`

Go to **Project Settings → API keys** and fill these into your `.env`:

| Supabase value | `.env` keys |
|---|---|
| Project URL | `SUPABASE_URL` **and** `NEXT_PUBLIC_SUPABASE_URL` |
| `anon` / publishable key | `SUPABASE_ANON_KEY` **and** `NEXT_PUBLIC_SUPABASE_ANON_KEY` |
| `service_role` / secret key | `SUPABASE_SERVICE_ROLE_KEY` |

The `service_role` key bypasses row-level security entirely. It belongs to the backend
only. Never put it in a `NEXT_PUBLIC_*` variable — those are compiled into the browser
bundle and are readable by anyone who loads the page.

## 4. Configure auth URLs

Under **Authentication → URL Configuration**:

- **Site URL:** `http://localhost:3000`
- **Redirect URLs:** add both `http://localhost:3000/**` and `http://localhost:3005/**`

Then under **Authentication → Sign In / Providers**, make sure **Email** is enabled.
Password sign-in works out of the box. Magic links and OAuth need extra configuration
(SMTP credentials, or provider client IDs) and are optional.

If you skip this step, login appears to succeed and then bounces you back to the login
page — the redirect is rejected by Supabase, not by the app.

## 5. Create your first recruiter

Sign up through the landing app at `http://localhost:3000` once the stack is running.
The backend creates your profile on first login.

Self-hosted instances are not invite-gated by default (`SIGNUP_INVITE_ONLY=false` in
`.env`). Set it to `true` if you want to close signup on a shared deployment.

To make yourself a staff user, run this in the SQL editor after signing up:

```sql
UPDATE public.profiles SET is_staff = true WHERE email = 'you@example.com';
```

## Troubleshooting

**"relation does not exist" when the app loads.** `schema.sql` did not finish. Re-run it
and read the error — the SQL editor stops at the first failure.

**Login loops back to the login page.** Step 4 — the redirect URLs are missing.

**Logged in, but every list is empty.** Expected on a fresh instance: row-level security
scopes all data to your profile's organization. Either create a requisition through the
app, or run the ATTACH statement at the bottom of `seed.sql`.

**`permission denied for schema public` while running `schema.sql`.** You are running as
something other than the project owner. Use the dashboard SQL editor rather than an
external client.
