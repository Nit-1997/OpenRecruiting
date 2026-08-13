# The setup wiki

Status: approved, not implemented
Date: 2026-08-12

## Why

Someone who clones this repo cannot currently set it up. `docs/setup/` covers
Supabase and Recall; nothing covers Cloudflare, Deepgram, email or Google auth,
and no page sequences them. That is the gap between "the code is published" and
"the project can be used".

This is sub-project **B** of three. **A** (setup-UI completeness) is done and
committed. **C** is an agent skill that walks a user through this wiki and
verifies each step. B goes second so it describes A's finished behaviour, and
its structure is what C executes.

## Positioning change

The README currently says:

> This is an **archived reference release** — it is not maintained and issues
> may not be answered.

That is being retired. OpenRecruiting is a project people are meant to run, so
the wiki is a real onboarding path — full troubleshooting, every provider
covered, written so a non-expert succeeds without help. The banner becomes a
plain statement of best-effort support.

Retaining "archived and unmaintained" alongside a hand-held setup wiki would be
incoherent: most readers would not attempt setup at all, and the effort would be
spent on an audience that had already left.

## What is actually required

The single most important correction in this work. The stack **boots** with most
keys unset, and the existing docs generalise that into "everything except the
database is optional". That is false about *using* the product, and it is the
kind of false that sends someone to an empty dashboard concluding the project is
thin.

**Required to run a meaningful session:**

| Provider | Why it cannot be skipped |
|---|---|
| Supabase | database and auth |
| Anthropic (or another model key) | AI intake, feedback, screening |
| Deepgram | speech-to-text; without it the voice agent cannot transcribe |
| Recall.ai | meeting capture — joins the call, produces the transcript |
| Cloudflare tunnel | Recall is cloud-only and calls back into the instance |
| Cloudflare TURN | a Recall bot's media is UDP; no HTTP tunnel carries it |
| Resend (or Zoho) | interview invitations, feedback links, password resets |

**Genuinely optional:** Google OAuth (email/password works without it), which
model each workload uses (every alias has a working default), and the Cortex MCP
connector.

## Structure

```
SETUP.md                     the spine, repo root, linked from README
docs/setup/supabase.md       exists — correct
docs/setup/recall.md         exists — correct
docs/setup/cloudflare.md     new — domain, tunnel, TURN
docs/setup/ai-keys.md        new — Anthropic, Deepgram, OpenAI
docs/setup/email.md          new — Resend, with Zoho as the alternative
docs/setup/google-auth.md    new — optional
```

The spine **sequences**; the pages **instruct**. One place per fact, so nothing
drifts. Cloudflare's three pieces share a page because they are one account and
one dashboard session. The three AI keys share a page because each is "sign up,
copy the key" — separate files would be padding.

## The spine

One configuration pass, chosen deliberately over an early working-login
checkpoint. The trade is stated in the file itself: nothing proves the product
works until step 8, so step 8 must be concrete.

| Step | Ends with |
|---|---|
| 1. What you'll need | the seven accounts listed upfront, with rough cost and time |
| 2. Create accounts, collect credentials | every value in hand (links to provider pages) |
| 3. `docker compose up -d --build` | stack running, unconfigured |
| 4. `:3010` — paste everything, apply | `.env` written, affected services recreated |
| 5. Apply `schema.sql` | 48 tables; the UI's re-check goes green |
| 6. Staff user via `staff_user.sql` | admin login works at `:3001` |
| 7. First org, invite, credit budget | a recruiter can sign in |
| 8. Run a real session | intake → schedule → bot joins → transcript → feedback |

### Why this order works despite the dependency loop

Recall's webhooks must be registered against a hostname that exists, and the
tunnel only carries traffic once the stack is up. Creating the tunnel in
Cloudflare's dashboard yields both the hostname and the token *before* anything
runs, so step 2 can register Recall webhooks against a hostname that is not yet
live, and step 4 makes it live. The spine states this explicitly, because it
looks like a circular dependency and is not.

Schema-before-apps is the other ordering trap. The apps are running from step 3
but have no tables until step 5; the setup UI's schema check cannot report
anything until the Supabase keys are entered at step 4. So the real sequence is:
enter keys → the UI reports "not applied" → apply → re-check. The spine says
this rather than leaving the reader to discover it.

## Page anatomy

Every provider page follows one shape, taken from the existing `recall.md`,
which already does this well:

1. **What this gets you** — one paragraph, concrete.
2. **Steps** — numbered, with the exact dashboard navigation.
3. **Verify** — a command and its expected output.
4. **What breaks without it** — the specific failure, not "it won't work".
5. **Troubleshooting** — symptom → cause, for the failures actually seen.

The Verify block is load-bearing for C: it is what the agent runs to decide
whether a step succeeded. `recall.md`'s existing example is the model:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://localhost:8004/api/v2/webhooks/recall/bot-status \
  -H 'Content-Type: application/json' -d '{}'
# 401
```

A `401` is the healthy answer — signature verification is on. Every page needs an
equivalent: an observable check with an unambiguous expected result.

## Corrections to existing content

Not additions — the current text is wrong in ways that will mislead.

**README**
- "Every dependency except the database is optional" → the required seven and
  the optional three.
- "On a laptop that means `ngrok http 8004`" → the stack ships `cloudflared`
  plus Caddy path-routing on one hostname. `ngrok` is a different, undocumented
  path that does not produce the routing the frontends expect.
- The archived-release banner, per the positioning change above.

**docs/setup/recall.md**
- "It is entirely optional: the platform runs fine without it" → it boots
  without it; you cannot run a session.
- Step 3 tells the reader to run `ngrok` or an ad-hoc `cloudflared tunnel --url`.
  Replace with the bundled tunnel, and cross-link `cloudflare.md`.

**docs/setup/supabase.md**
- calls `schema.sql` "idempotent"; it is now guarded and refuses a second run;
- troubleshooting says "re-run it and read the error", which the guard now
  refuses — the correct advice is that a failed apply rolled back completely, so
  fix the cause and run it once more;
- describes the admin portal as "customers, subscriptions, promotions, blog and
  assessments"; subscriptions and promotions are deleted and assessments is
  unlinked;
- every one of its five schema counts is wrong.

**Drop the precise counts.** The page claims the schema creates "53 tables, 178
functions, 89 row-level-security policies, 222 indexes and 25 triggers". Measured
against the file:

| | claimed | actual |
|---|---|---|
| tables | 53 | 48 |
| policies | 89 | 80 |
| functions | 178 | **61** |
| indexes | 222 | **136** |
| triggers | 25 | **18** |

Tables and policies drifted in this session's teardown. Functions, indexes and
triggers were already wrong before it — the page has been carrying stale numbers
for some time without anyone noticing, which is exactly what makes them worthless
as reassurance.

The corrected page states no counts. The reader's actual question is "did it
work?", which the guard, the transaction and the setup UI's schema check all
answer directly. A number nobody verifies is a liability, not information.

## Correction back into sub-project A

`readiness.py` renders an unset required feature as `dormant`, which the panel
labels "off" — reading as *off by choice*. With the required/optional split
above, that understates a half-configured instance.

Add a `required: bool` to the feature spec. The panel then distinguishes
"required — not configured" from "optional — off", and its summary pill counts
only required gaps. `test_readiness.py` gains a case asserting that every member
of the required seven is marked required, so the list cannot silently drift from
this spec.

## Verification

Documentation cannot be unit-tested, so the checks are:

1. **Every command in every page is run** during implementation, and its real
   output pasted — no invented expected values.
2. **Link check** — every relative link resolves; no page references a deleted
   route such as `/subscriptions`.
3. **Fact check against code** — port numbers, variable names and endpoint paths
   are grepped from the repo, not recalled. No counts are stated at all.
4. **The required-seven list matches `readiness.py`** in both directions.

Full clean-room validation — a fresh Supabase project, a new Cloudflare account
— is out of scope here; it needs accounts this work cannot create. C is where
that gets exercised for real.

## Risks

**The wiki drifts from the code.** Already demonstrated: three of `supabase.md`'s
five schema counts were wrong before this session began. Mitigated by removing
unverifiable numbers entirely, grepping rather than copying, and keeping each
fact in exactly one page.

**One config pass means late failure.** Accepted deliberately. Step 8 must
therefore be a concrete end-to-end script, and the readiness panel is what
narrows a late failure to the feature that caused it.

**Cost is not stated anywhere today.** Seven accounts, several billable. Step 1
names which have free tiers and which do not, so nobody discovers this at step 6.
