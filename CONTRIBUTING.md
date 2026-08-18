# Contributing

PRs are welcome. Support is best-effort and issues may take a while, but this
project is meant to be run, not just read.

## Before you open a PR

- **Commits follow [Conventional Commits](https://www.conventionalcommits.org/)**
  — `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`. The scope is
  usually the service (`fix(setup-ui):`, `feat(backend):`).
- **Run `make verify`** to health-check the stack, and the suite for whatever you
  touched: `make test` (backend), `make test-cortex`, or the package's own
  `pytest` / `npm test`. Run `npm run build` for any changed Next.js app.
- **Never commit secrets.** `.env` is git-ignored; `.env.example` is the
  template. New configuration belongs there with a comment saying what it does
  and what breaks when it is unset.

## What CI enforces

Two workflows run on every push and PR.

**`tests.yml`** runs every suite in the repo — eight Python packages in a
matrix, `backend` and `cortex-backend` in their test images, and `landing`
(tests plus build, because that app inlines `NEXT_PUBLIC_` values at build time,
so a config mistake fails the build rather than a unit test). All block a merge.

`recruiter-app` runs but is **non-blocking**: 1278 of its 1281 tests pass and
three fail deterministically on `main`. They are neither skipped nor deleted —
skipping would hide three real breaks, blocking would make every unrelated PR
red. Fix them, then remove `continue-on-error` from that job.

**`gate.yml`** is three release gates, and all three block a merge:

| Gate | What fails it |
|---|---|
| `debrand` | Any reference to the pre-open-source product name, in file **contents or filenames**, outside `NOTICE`, `README.md` and `docs/superpowers/{specs,plans}/`. |
| `secrets` | [gitleaks](https://github.com/gitleaks/gitleaks) over the **full history**, not just the tip. A secret in an earlier commit fails the run even after it is deleted. |
| `no-captured-interviews` | Anything committed under `workers/feedback-agent/evals/{fixtures,runs}/`. These hold real transcripts and real people's names; they are git-ignored, but `git add --force` would slip past that. |

## Versioning

[Semantic Versioning](https://semver.org/). Given this is a self-hosted stack,
"breaking" means something an operator has to act on:

- **MAJOR** — a database migration that is not backward compatible, a removed or
  renamed `.env` variable, or a change that makes an existing deployment stop
  working until the operator intervenes.
- **MINOR** — new features, new optional `.env` variables, new services.
- **PATCH** — fixes and docs that need nothing from the operator.

Notable changes go in [CHANGELOG.md](CHANGELOG.md) under `## [Unreleased]` as
part of the PR that makes them. A release moves that block under a version
heading and tags it.

## House conventions

These are not style preferences; each one exists because its absence caused a
bug that took a while to find.

- **Comments explain *why*, not *what*.** Several comments in this repo are the
  only surviving record of a decision that is expensive to re-derive and cheap
  to undo by accident. If you delete one, say why in the PR.
- **A guard that is documented must be implemented.** A comment claiming the
  code refuses something, where nothing refuses it, is worse than no comment.
- **Generated files must be reproducible from committed inputs.**
  `litellm-config.yaml` is rendered from `setup-ui/app/workloads.py` plus
  `llm-providers.json`; do not hand-edit it, and do not commit output built from
  a local config that is git-ignored.
- **Status surfaces must not claim more than they measured.** "The key is set"
  is not "the key works". This codebase has produced that bug repeatedly — see
  `setup-ui/app/readiness.py` and `setup-ui/app/probe.py` for the shape of the
  fix.
- **Every HTML element gets a unique `id`.**
- **A config change needs a container RECREATE, not a restart** — `env_file` is
  read at container create time, so a restart silently reuses the old values.
