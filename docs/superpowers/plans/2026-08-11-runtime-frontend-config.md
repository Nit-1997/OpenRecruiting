# Runtime Frontend Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every browser-visible setting apply on a container **restart** instead of an image **rebuild**, so that changing `NEXT_PUBLIC_SUPABASE_URL` in `.env` and running `docker compose up -d` actually reaches the browser.

**Architecture:** Next.js inlines `process.env.NEXT_PUBLIC_*` into the client bundle at build time. All four frontends set `output: 'standalone'`, so a Node server runs at request time and `process.env` is live server-side. Each app's root layout therefore reads the values server-side and emits them once as `window.__OR_CONFIG__`; client code reads that object instead of `process.env`. **The variables keep their existing names in `.env`** — only the *client-side references* change — so no `.env`, compose, or deploy-config edits are required. Removing the build `ARG`s from the Dockerfiles is what stops the stale values being baked in.

**Tech Stack:** Next.js 15 App Router (`output: 'standalone'`), React 19, TypeScript, bun test, Docker Compose.

**Source spec:** `docs/superpowers/specs/2026-08-11-self-host-settings-ui-design.md` (fact 5, decision D6)

## Global Constraints

- **Every HTML element added anywhere in this project must carry a unique `id`.** (Project-wide rule from `CLAUDE.md`.)
- **`npm run build` (or `bun run build`) must pass before committing** any change to a Next.js app.
- **Never commit API keys, secrets, certs, or `.env` files.**
- **Only PUBLIC values may enter `window.__OR_CONFIG__`.** It is serialised into HTML that any visitor can read. A service key reaching it is a credential disclosure, not a bug. Task 1 adds a test that fails on any key whose name suggests a secret.
- **Commit after each task with a meaningful message. Self-review the diff first** (`git diff --cached`).
- **Rebuild and restart containers after each task** that touches a Dockerfile or app source: `docker compose up -d --build <service>`.
- Baselines that must not regress: `recruiter-app` **1271 pass / 2 known-flaky fails** (`cd recruiter-app && bun test`), `landing` **31 passed** (`cd landing && npx vitest run`). The 2 recruiter-app failures are the pre-existing flaky `composer.test.tsx` pair — do not chase them and do not attribute them to this work.

---

## File Structure

| Path | Change | Task |
|---|---|---|
| `recruiter-app/src/lib/runtime-config.ts` | **new** — the isomorphic reader + the server payload builder | 1 |
| `recruiter-app/src/lib/__tests__/runtime-config.test.ts` | **new** — 6 tests incl. the secret-leak guard | 1 |
| `recruiter-app/src/app/layout.tsx` | emit `window.__OR_CONFIG__` | 1 |
| `recruiter-app/src/lib/supabase.ts` | read runtime config, not `process.env` | 2 |
| `recruiter-app/src/components/shell/app-shell.tsx` | same | 2 |
| `recruiter-app/src/components/shell/profile-popover.tsx` | same | 2 |
| `recruiter-app/src/app/login/page.tsx` | same | 2 |
| `recruiter-app/src/components/sub-agents/intake/IntakeCallProvider.tsx` | same | 2 |
| `recruiter-app/src/components/feedback/feedback-call-provider.tsx` | same | 2 |
| `recruiter-app/src/components/screening/screening-call-provider.tsx` | same | 2 |
| `recruiter-app/src/lib/__tests__/no-build-time-config.test.ts` | **new** — the regression guard | 2 |
| `recruiter-app/Dockerfile` | drop the 7 build `ARG`/`ENV` lines | 3 |
| `landing`, `admin-app`, `voice-frontend` equivalents | same treatment | 4 |

---

### Task 1: The runtime config module and server injection

Nothing reads it yet. This task builds the mechanism and proves it cannot leak a secret.

**Files:**
- Create: `recruiter-app/src/lib/runtime-config.ts`
- Create: `recruiter-app/src/lib/__tests__/runtime-config.test.ts`
- Modify: `recruiter-app/src/app/layout.tsx`

**Interfaces:**
- Produces: `getRuntimeConfig(): RuntimeConfig` (isomorphic — safe in server and client components); `serverRuntimeConfig(): RuntimeConfig` (server only); `RUNTIME_CONFIG_SCRIPT_ID = 'runtime-config'`; type `RuntimeConfig`.

- [ ] **Step 1: Record the baseline**

```bash
cd recruiter-app && bun test 2>&1 | tail -5
```
Expected: **1271 pass, 2 fail** (the known-flaky `composer.test.tsx` pair). Paste the count. Do not build on an unrecorded baseline.

- [ ] **Step 2: Write the failing test**

Create `recruiter-app/src/lib/__tests__/runtime-config.test.ts`:

```typescript
import { describe, expect, it, afterEach } from 'bun:test';
import { serverRuntimeConfig, getRuntimeConfig, RUNTIME_CONFIG_KEYS } from '../runtime-config';

const ORIGINAL = { ...process.env };

afterEach(() => {
  process.env = { ...ORIGINAL };
  delete (globalThis as Record<string, unknown>).__OR_CONFIG__;
});

describe('serverRuntimeConfig', () => {
  it('reads the existing NEXT_PUBLIC_ names so .env does not have to change', () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://proj.supabase.co';
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'anon-key';

    const cfg = serverRuntimeConfig();

    expect(cfg.supabaseUrl).toBe('https://proj.supabase.co');
    expect(cfg.supabaseAnonKey).toBe('anon-key');
  });

  it('accepts PUBLISHABLE as an alias for ANON, as supabase.ts already does', () => {
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = 'publishable-key';
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

    expect(serverRuntimeConfig().supabaseAnonKey).toBe('publishable-key');
  });

  it('emits empty strings rather than undefined for unset values', () => {
    for (const key of Object.keys(process.env)) {
      if (key.startsWith('NEXT_PUBLIC_')) delete process.env[key];
    }

    const cfg = serverRuntimeConfig();

    // An unconfigured stack must still render. Callers decide what to do about
    // a blank value; `undefined` would JSON-serialise the key away entirely and
    // turn a missing setting into a missing property.
    expect(cfg.supabaseUrl).toBe('');
    expect(cfg.landingUrl).toBe('');
  });

  it('NEVER exposes a value whose name suggests a secret', () => {
    // window.__OR_CONFIG__ is serialised into HTML any visitor can read. This is
    // the guard for the one mistake that turns this mechanism into a credential
    // disclosure. It is keyed on the SOURCE env var names, not the output.
    const forbidden = /SECRET|SERVICE_KEY|PRIVATE|PASSWORD|TOKEN/i;
    const leaked = RUNTIME_CONFIG_KEYS.filter((envName) => forbidden.test(envName));

    expect(leaked).toEqual([]);
  });

  it('only ever reads NEXT_PUBLIC_-prefixed variables', () => {
    const unprefixed = RUNTIME_CONFIG_KEYS.filter((k) => !k.startsWith('NEXT_PUBLIC_'));

    expect(unprefixed).toEqual([]);
  });
});

describe('getRuntimeConfig', () => {
  it('prefers the injected window object when one is present', () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://from-env.supabase.co';
    (globalThis as Record<string, unknown>).__OR_CONFIG__ = {
      supabaseUrl: 'https://from-window.supabase.co',
    };

    // On the client the bundle has no live process.env, so the injected object
    // is the only real source. Preferring it also means a server-rendered pass
    // and a client pass agree.
    expect(getRuntimeConfig().supabaseUrl).toBe('https://from-window.supabase.co');
  });
});
```

- [ ] **Step 3: Run it and confirm it fails**

```bash
cd recruiter-app && bun test src/lib/__tests__/runtime-config.test.ts
```
Expected: FAIL — `Cannot find module '../runtime-config'`.

- [ ] **Step 4: Write the module**

Create `recruiter-app/src/lib/runtime-config.ts`:

```typescript
/**
 * Browser-visible configuration, resolved at RUNTIME rather than build time.
 *
 * Why this exists. Next.js inlines `process.env.NEXT_PUBLIC_*` into the client
 * bundle when `next build` runs, so changing one of those values and restarting
 * the container does nothing — the old value is already compiled into the
 * JavaScript served to the browser. Nine such variables exist across this repo
 * and two of them are the Supabase URL and anon key, which means a self-hoster
 * could paste correct credentials, watch the backend start working, and still
 * be unable to log in, with nothing anywhere explaining why.
 *
 * `next.config.ts` sets `output: 'standalone'`, so a Node server runs at request
 * time and `process.env` IS live server-side. The root layout reads these values
 * there and emits them once as `window.__OR_CONFIG__`; client code reads that.
 * A restart is then enough.
 *
 * The variables keep their `NEXT_PUBLIC_` names in `.env` on purpose — this
 * change is about WHERE they are read, not what they are called, and renaming
 * them would churn every deploy environment for no benefit.
 *
 * SECURITY: everything here is serialised into HTML that any visitor can read.
 * Only public values may be added. `runtime-config.test.ts` fails the build if a
 * key name suggests a secret.
 */

export interface RuntimeConfig {
  supabaseUrl: string;
  supabaseAnonKey: string;
  cookieDomain: string;
  apiUrl: string;
  apiV2Url: string;
  appUrl: string;
  landingUrl: string;
  assessmentUiUrl: string;
  intakeVoiceOfferUrl: string;
  feedbackVoiceOfferUrl: string;
  screeningVoiceOfferUrl: string;
}

/** Every env var this module reads. The tests assert every entry is
 *  NEXT_PUBLIC_-prefixed and none looks like a secret. */
export const RUNTIME_CONFIG_KEYS = [
  'NEXT_PUBLIC_SUPABASE_URL',
  'NEXT_PUBLIC_SUPABASE_ANON_KEY',
  'NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY',
  'NEXT_PUBLIC_COOKIE_DOMAIN',
  'NEXT_PUBLIC_API_URL',
  'NEXT_PUBLIC_API_V2_URL',
  'NEXT_PUBLIC_APP_URL',
  'NEXT_PUBLIC_LANDING_URL',
  'NEXT_PUBLIC_ASSESSMENT_UI_URL',
  'NEXT_PUBLIC_INTAKE_VOICE_OFFER_URL',
  'NEXT_PUBLIC_FEEDBACK_VOICE_OFFER_URL',
  'NEXT_PUBLIC_SCREENING_VOICE_OFFER_URL',
] as const;

export const RUNTIME_CONFIG_SCRIPT_ID = 'runtime-config';

/** The global the layout writes and the client reads. */
const GLOBAL_KEY = '__OR_CONFIG__';

/** SERVER ONLY. Reads live process.env. Safe in server components, route
 *  handlers and middleware; returns blanks if called in the browser. */
export function serverRuntimeConfig(): RuntimeConfig {
  const env = (name: string): string => process.env[name] ?? '';
  return {
    supabaseUrl: env('NEXT_PUBLIC_SUPABASE_URL'),
    // supabase rebranded "anon public" -> "publishable"; same key, two names.
    supabaseAnonKey:
      env('NEXT_PUBLIC_SUPABASE_ANON_KEY') || env('NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY'),
    cookieDomain: env('NEXT_PUBLIC_COOKIE_DOMAIN'),
    apiUrl: env('NEXT_PUBLIC_API_URL'),
    apiV2Url: env('NEXT_PUBLIC_API_V2_URL'),
    appUrl: env('NEXT_PUBLIC_APP_URL'),
    landingUrl: env('NEXT_PUBLIC_LANDING_URL'),
    assessmentUiUrl: env('NEXT_PUBLIC_ASSESSMENT_UI_URL'),
    intakeVoiceOfferUrl: env('NEXT_PUBLIC_INTAKE_VOICE_OFFER_URL'),
    feedbackVoiceOfferUrl: env('NEXT_PUBLIC_FEEDBACK_VOICE_OFFER_URL'),
    screeningVoiceOfferUrl: env('NEXT_PUBLIC_SCREENING_VOICE_OFFER_URL'),
  };
}

/** Isomorphic. Use this everywhere except the layout that does the injecting.
 *  Prefers the injected object so a server pass and a client pass agree. */
export function getRuntimeConfig(): RuntimeConfig {
  const injected = (globalThis as Record<string, unknown>)[GLOBAL_KEY] as
    | Partial<RuntimeConfig>
    | undefined;
  if (injected) {
    return { ...serverRuntimeConfig(), ...injected };
  }
  return serverRuntimeConfig();
}

/** The exact string the layout injects. Exported so a test can assert the
 *  payload without rendering React. */
export function runtimeConfigScript(config: RuntimeConfig): string {
  // JSON.stringify does NOT escape `<`, so a value containing "</script>" would
  // terminate the tag early and inject arbitrary markup. Escaping every `<` as
  // < is the standard fix and is still valid JS inside the string literal.
  const json = JSON.stringify(config).replace(/</g, '\\u003c');
  return `window.${GLOBAL_KEY}=${json};`;
}
```

- [ ] **Step 5: Run the tests**

```bash
cd recruiter-app && bun test src/lib/__tests__/runtime-config.test.ts
```
Expected: **6 pass**.

- [ ] **Step 6: Inject it from the root layout**

In `recruiter-app/src/app/layout.tsx`, add the import beside the existing ones:

```typescript
import { RUNTIME_CONFIG_SCRIPT_ID, runtimeConfigScript, serverRuntimeConfig } from '@/lib/runtime-config';
```

Then, as the **first child inside `<head>`** (before any other script so it is defined before hydration):

```tsx
        <script
          id={RUNTIME_CONFIG_SCRIPT_ID}
          dangerouslySetInnerHTML={{ __html: runtimeConfigScript(serverRuntimeConfig()) }}
        />
```

If the layout has no explicit `<head>`, place it as the first child of `<body>` instead — App Router hoists it either way. The `id` satisfies the project-wide unique-id rule.

- [ ] **Step 7: Build, run the suite, and commit**

```bash
cd recruiter-app && bun run build && bun test 2>&1 | tail -5
```
Expected: build succeeds; **1271 pass, 2 fail** + 6 new = paste the exact line.

```bash
git add recruiter-app/src/lib/runtime-config.ts recruiter-app/src/lib/__tests__/runtime-config.test.ts recruiter-app/src/app/layout.tsx
git diff --cached
git commit -m "feat(recruiter-app): resolve browser config at runtime instead of build time"
```

---

### Task 2: Move every client-side reader onto it

Seven files read `process.env.NEXT_PUBLIC_*` from client code today. Server-side readers (`middleware.ts`, `lib/supabase-server.ts`, `app/api/deepgram/route.ts`) are **left alone** — they already see live env and changing them would be churn.

**Files:**
- Modify: `recruiter-app/src/lib/supabase.ts`, `src/components/shell/app-shell.tsx`, `src/components/shell/profile-popover.tsx`, `src/app/login/page.tsx`, `src/components/sub-agents/intake/IntakeCallProvider.tsx`, `src/components/feedback/feedback-call-provider.tsx`, `src/components/screening/screening-call-provider.tsx`
- Create: `recruiter-app/src/lib/__tests__/no-build-time-config.test.ts`

**Interfaces:**
- Consumes: `getRuntimeConfig()` from Task 1.

- [ ] **Step 1: Write the regression guard first**

Create `recruiter-app/src/lib/__tests__/no-build-time-config.test.ts`:

```typescript
import { describe, expect, it } from 'bun:test';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const SRC = join(import.meta.dir, '..', '..');

/** Server-side files legitimately read live process.env — a Node server runs at
 *  request time, so these are NOT baked into the client bundle. */
const SERVER_SIDE_ALLOWED = [
  'middleware.ts',
  'lib/supabase-server.ts',
  'app/api/deepgram/route.ts',
  'lib/runtime-config.ts',
];

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === 'node_modules' || entry === '__tests__') continue;
      walk(full, out);
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

describe('build-time config', () => {
  it('is not read by any client-side module', () => {
    // Next.js inlines process.env.NEXT_PUBLIC_* into the client bundle at BUILD
    // time. Any client module reading it is a value that a container restart
    // cannot change — the failure that makes a correct .env look broken.
    const offenders = walk(SRC)
      .filter((f) => !SERVER_SIDE_ALLOWED.some((a) => f.endsWith(a)))
      .filter((f) => !f.includes('/test/'))
      .filter((f) => readFileSync(f, 'utf8').includes('process.env.NEXT_PUBLIC_'))
      .map((f) => f.slice(SRC.length + 1));

    expect(offenders).toEqual([]);
  });
});
```

- [ ] **Step 2: Run it and record which files fail**

```bash
cd recruiter-app && bun test src/lib/__tests__/no-build-time-config.test.ts
```
Expected: FAIL listing the 7 client files. **Paste the list** — that is the task's work queue.

- [ ] **Step 3: Convert `lib/supabase.ts`**

Replace the three module-level reads:

```typescript
const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
```

with a read **inside** `getSupabaseClient()` (module scope runs before the injected script on some paths; function scope always runs after hydration):

```typescript
import { getRuntimeConfig } from '@/lib/runtime-config';
```

```typescript
export function getSupabaseClient(): SupabaseClient {
  if (_client) return _client;
  const { supabaseUrl: url, supabaseAnonKey: anonKey, cookieDomain } = getRuntimeConfig();
  if (!url || !anonKey) {
    throw new Error(
      'Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and ' +
        'NEXT_PUBLIC_SUPABASE_ANON_KEY (or _PUBLISHABLE_KEY) and restart the ' +
        'recruiter-app container — these are read at runtime, so no rebuild is needed.',
    );
  }
  ...
```

and delete the now-unused `const cookieDomain = process.env.NEXT_PUBLIC_COOKIE_DOMAIN;` line further down, using the destructured `cookieDomain` instead.

- [ ] **Step 4: Convert the remaining six**

Each is a one-line swap of the same shape. Replace
`process.env.NEXT_PUBLIC_LANDING_URL || 'http://localhost:3000'` with
`getRuntimeConfig().landingUrl || 'http://localhost:3000'`, adding
`import { getRuntimeConfig } from '@/lib/runtime-config';` to each file:

- `src/components/shell/app-shell.tsx:50` — `landingUrl`
- `src/components/shell/profile-popover.tsx:65` — `landingUrl`
- `src/app/login/page.tsx:14` — `landingUrl`
- `src/components/sub-agents/intake/IntakeCallProvider.tsx:46` — `intakeVoiceOfferUrl`
- `src/components/feedback/feedback-call-provider.tsx:62` — `feedbackVoiceOfferUrl`
- `src/components/screening/screening-call-provider.tsx:66` — `screeningVoiceOfferUrl`

Keep every existing `|| 'http://localhost:...'` fallback exactly as it is — those defaults are what make an unconfigured stack still render.

- [ ] **Step 5: Run the guard and the full suite**

```bash
cd recruiter-app && bun test src/lib/__tests__/no-build-time-config.test.ts && bun test 2>&1 | tail -5
```
Expected: guard passes; suite **1271 pass, 2 fail** + 7 new. Paste the exact line.

- [ ] **Step 6: Build and commit**

```bash
cd recruiter-app && bun run build
git add recruiter-app/src
git diff --cached
git commit -m "refactor(recruiter-app): read browser config from the runtime object, not the bundle"
```

---

### Task 3: Stop baking the values into the image, and prove a restart applies them

**Files:**
- Modify: `recruiter-app/Dockerfile:17-24`

- [ ] **Step 1: Remove the build ARGs**

Delete the seven `ARG NEXT_PUBLIC_*` lines (`:17-23`) and the `ENV NEXT_PUBLIC_...` block (`:24-30`) that precedes `RUN bun run build`. Replace with a comment:

```dockerfile
# No NEXT_PUBLIC_* build args. Next.js inlines those into the CLIENT BUNDLE at
# build time, which froze every browser-visible setting into the image — a
# changed .env then needed a rebuild, not a restart, and nothing said so. They
# are now read at request time by the Node server (output: 'standalone') and
# injected as window.__OR_CONFIG__ by src/app/layout.tsx. See
# src/lib/runtime-config.ts. Re-adding an ARG here silently restores the bug.
```

**`docker-compose.yml` also passes `build.args` to `recruiter-app` — verified, it does. Remove that `args:` block too**, or the compose build keeps feeding values the Dockerfile no longer declares, which Docker warns about but does not fail on. (`landing` and `admin-app` have one as well; `voice-frontend` does not.)

- [ ] **Step 2: Rebuild and prove the mechanism live**

This is the step that actually verifies the task; the unit tests cannot.

```bash
docker compose up -d --build recruiter-app
curl -s http://localhost:3005/login | grep -o 'window.__OR_CONFIG__={[^<]*' | head -c 300
```
Expected: the injected script contains the CURRENT `.env` value of `NEXT_PUBLIC_SUPABASE_URL`.

Now change it without rebuilding:

```bash
cp .env .env.bak
sed -i '' 's|^NEXT_PUBLIC_APP_URL=.*|NEXT_PUBLIC_APP_URL=http://restart-proved-it:9999|' .env
docker compose up -d recruiter-app          # restart only, NO --build
sleep 5
curl -s http://localhost:3005/login | grep -c 'restart-proved-it'
cp .env.bak .env && rm .env.bak && docker compose up -d recruiter-app
```
Expected: the grep returns **1**. Before this task it would have returned 0. **Paste both results** — this is the proof the whole plan exists for.

- [ ] **Step 3: Commit**

```bash
git add recruiter-app/Dockerfile docker-compose.yml
git diff --cached
git commit -m "build(recruiter-app): stop baking browser config into the image"
```

Commit body must carry the before/after grep counts from Step 2.

---

### Task 4: The other three frontends

`landing`, `admin-app` and `voice-frontend` have the same wound. Repeat Tasks 1–3 for each, in that order, **one commit per app**.

**Measured before planning — this task is larger than `recruiter-app` was, so do not treat it as a copy-paste:**

| app | `process.env.NEXT_PUBLIC_` reads (non-test) | build `ARG`s | compose `build.args` |
|---|---|---|---|
| `landing` | 26 | 7 | yes |
| `admin-app` | 39 | 5 | yes |
| `voice-frontend` | 2 | **0** | no |

Those counts include **server-side** readers, which stay as they are — Step 1 below is what separates them. `voice-frontend` is the odd one: it has no build ARGs at all, so its `NEXT_PUBLIC_*` values are already `undefined` in the bundle and it has been silently running on its hardcoded fallbacks. Converting it is a correctness fix, not just a config-plumbing one.

Given the size, `landing` and `admin-app` each deserve their own execution session; do not batch all three.

**Files:** the `src/lib/runtime-config.ts`, `src/lib/__tests__/runtime-config.test.ts`, root `layout.tsx`, client readers, and `Dockerfile` of each app.

- [ ] **Step 1: Establish each app's reader list before changing it**

```bash
for app in landing admin-app voice-frontend; do
  echo "=== $app ==="
  grep -rn "process.env.NEXT_PUBLIC_" $app/src --include="*.ts" --include="*.tsx" \
    | grep -v "__tests__\|\.test\." || echo "  none"
  echo "--- build args ---"
  grep -n "ARG NEXT_PUBLIC" $app/Dockerfile || echo "  none"
done
```

Paste the output. **An app with no client-side readers needs only its Dockerfile ARGs removed** — do not add a `runtime-config.ts` it has no use for (YAGNI).

- [ ] **Step 2: For each app that needs it, copy the Task 1 module**

`runtime-config.ts` is per-app because each has a different set of values. Copy it, then **delete the fields that app does not use** and trim `RUNTIME_CONFIG_KEYS` to match — the "only NEXT_PUBLIC_" and "no secrets" tests come along with it and must still pass.

- [ ] **Step 3: Per app — convert readers, remove ARGs, rebuild, prove**

Run the same live proof as Task 3 Step 2 against each app's port (`landing` 3000, `admin-app` 3001, `voice-frontend` 3003), using a variable that app actually reads. Paste each result.

- [ ] **Step 4: Full regression**

```bash
cd landing && npx vitest run 2>&1 | tail -3        # 31 passed
cd ../recruiter-app && bun test 2>&1 | tail -3     # 1271 pass, 2 known-flaky
docker compose up -d --build && make verify        # all services ok
```

- [ ] **Step 5: Commit per app**

```bash
git add <app>/
git diff --cached
git commit -m "build(<app>): read browser config at runtime, not build time"
```

---

## Definition of done

- `grep -rn "process.env.NEXT_PUBLIC_" */src --include="*.ts" --include="*.tsx" | grep -v test` returns **only** the documented server-side readers (`middleware.ts`, `lib/supabase-server.ts`, `app/api/deepgram/route.ts`, and each `runtime-config.ts`).
- `grep -rn "ARG NEXT_PUBLIC" */Dockerfile` returns **nothing**.
- For each of the four apps: changing a `NEXT_PUBLIC_` value in `.env` and running `docker compose up -d <app>` **without `--build`** changes what the browser receives. Proven by the grep in Task 3 Step 2 and pasted in each commit.
- `window.__OR_CONFIG__` contains no secret. Pinned by `runtime-config.test.ts`.
- No client module reads `process.env.NEXT_PUBLIC_*`. Pinned by `no-build-time-config.test.ts`.
- `recruiter-app` **1271 pass / 2 known-flaky**, `landing` **31 passed**, `make verify` all services `ok`.
- Every new `<script>` carries a unique `id`.

## What this unblocks

`docs/superpowers/specs/2026-08-11-self-host-settings-ui-design.md` decision D6. Until this lands, the settings UI cannot set the Supabase URL the browser uses — it would report success while the browser kept stale values and login failed with no explanation. That is the single most likely way the setup experience would appear to work and not.
