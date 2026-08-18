# Changelog

Notable changes to OpenRecruiting. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/), where "breaking" means something a
self-hosting operator has to act on — see [CONTRIBUTING.md](CONTRIBUTING.md#versioning).

Entries below `## [Unreleased]` are added by the PR that makes the change. A
release moves that block under a version heading and tags it.

## [Unreleased]

### Added

- **Choose your own model provider.** Anthropic, OpenAI, OpenRouter (~400 models,
  open-weight included) and local Ollama. One card in the setup UI picks a
  provider, stores its key, and repoints all 27 gateway workloads at it.
- **Live model probe.** "Test this model" makes four real calls through the
  gateway — plain text, a native tool call with typed arguments, streaming, and
  multi-tool routing — and reports what the model actually did, with the cost.
  Catalogue metadata says what a model *claims*; this says what it *does*.
- **Per-workload overrides.** Any single workload can be pinned to a different
  provider and model without turning the other 26 into hand-managed entries.
- **Per-model compatibility settings, derived not hand-typed.** Reasoning effort
  is pinned or disabled from OpenRouter's published metadata, and `temperature`
  is dropped for OpenAI models that reject `temperature=0`.
- `OPENROUTER_API_KEY` in `.env.example` and the setup UI.
- `llm-providers.example.json` documenting the provider registry format.
- **CI now runs the test suites** (`.github/workflows/tests.yml`) — 3442 Python
  tests across ten packages plus landing's 32, where previously CI ran only the
  three release gates and no tests at all.
- A PR template, this changelog, and a versioning policy in `CONTRIBUTING.md`.
- `landing/package-lock.json`, so `npm ci` is reproducible. Generated on Linux:
  a lockfile built on macOS omits the other platforms' optional native bindings
  (npm/cli#4828) and breaks `npm ci` everywhere else.

### Changed

- **`litellm-config.yaml` is now generated**, not hand-written — rendered from
  `setup-ui/app/workloads.py` and `llm-providers.json`. A fresh clone with no
  registry file reproduces the previous configuration exactly.
- Readiness reports whether the *chosen* provider's credential is set, rather
  than assuming Anthropic. It also checks providers named by an override, and
  counts a base URL (Ollama) as a credential.
- Saving a provider key now recreates the gateway once instead of restarting it,
  waiting for health, and then recreating it.
- The live gateway suite takes `LIVE_HOSTED_ALIASES` / `LIVE_LOCAL_ALIAS`, so a
  candidate model can be measured without editing the file.

### Fixed

- A failed model-catalogue fetch was cached as an empty catalogue, so for 30
  seconds afterwards every caller read the outage as "this provider has no
  models" — and a save in that window wrote a gateway config with the per-model
  reasoning settings silently missing.
- Pinning a workload that streams *and* sends tools to a model without native
  function calling was accepted, and stopped that workload recording answers
  with no error anywhere. Now refused.
- Pinning a `local`-tier alias persisted, displayed as "pinned", and changed
  nothing in the gateway. Now refused.
- A malformed provider reply (HTTP 200 with no choices) crashed the probe with
  an unhandled 500 instead of reporting a failed check.
- Three `recruiter-app` tests failed on Linux (so, on every CI run) while passing
  on macOS. Neither was a product bug: the two Composer routing tests stubbed
  `globalThis.fetch` and depended on `@/lib/v2-client` being genuine, but seven
  test files mock it process-wide and `mock.module` is last-writer-wins, so
  `classifyAssistantIntent` fail-opened to `out_of_scope` and never routed. The
  `AtsUpdateChip` dismiss test used `waitFor`, which does not resolve on Linux
  even once its callback succeeds.
- Saving a provider key on a fresh clone wrote a one-line `.env`, permanently
  dropping every documented default from `.env.example`.
- The committed `litellm-config.yaml` carried routes generated from a
  git-ignored local file, so a fresh clone's gateway and setup UI disagreed
  about which providers existed.
- `landing/src/lib/backend-url.ts` carried a pre-open-source brand reference,
  which had been failing the `debrand` CI gate on every push since 2026-08-11.
- The `secrets` gate failed on every pull request — `gitleaks-action` requires
  `GITHUB_TOKEN` on `pull_request` events (it asks the API for the commit range)
  but not on `push` (it diffs locally), so the job passed on every push and broke
  the moment a PR was opened.

## [1.0.0] — 2026-08-13

First public release. Reconstructed from history; earlier detail lives in the
commit log.

### Added

- **Setup UI** — configure the whole stack from a browser instead of editing
  `.env`: grouped settings, a readiness panel saying which features are live and
  what each missing value costs, Supabase schema detection, and per-workload
  model selection.
- **Claude Code setup skill** — "help me set up OpenRecruiting" walks the guide,
  writes the config and verifies each step.
- **Public endpoints** — Caddy plus Cloudflare Tunnel, with TURN credentials
  minted per offer so meeting-bot voice works through NAT.
- **Remote MCP connector**, connectable from Claude.
- Setup wiki (`setup-wiki-docs/`) replacing `.env`-editing instructions.

### Changed

- Credits are held per organisation; plan tiers removed.
- Landing pages rewritten as an open-source project rather than a vendor.

### Removed

- The payment layer and its schema, in favour of a per-org credit budget.

## [0.1.0] — 2026-08-01

- Initial open-source publication under Apache-2.0, with CI release gates for
  secrets, captured interview data, and pre-open-source naming.

[Unreleased]: https://github.com/Nit-1997/OpenRecruiting/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Nit-1997/OpenRecruiting/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/Nit-1997/OpenRecruiting/releases/tag/v0.1.0
