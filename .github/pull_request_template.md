## What this changes

<!-- One or two sentences. What behaviour is different after this merges? -->

## Why

<!-- The problem, not the patch. If it fixes an issue, link it: Fixes #123 -->

## How to verify

<!-- The commands you actually ran, and what you saw. "Tests pass" is not
     verification; paste the count, or the before/after output. -->

```
```

## Checklist

- [ ] Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)
- [ ] Relevant suites run locally — `make test` (backend), `make test-cortex`, or the package's own `pytest` / `npm test`
- [ ] `npm run build` passes for any changed Next.js app (`landing`, `frontend`, `admin-app`)
- [ ] No secrets, API keys, certs or `.env` files — new config goes in `.env.example` with a comment explaining what it does
- [ ] No real candidate, interview or transcript data (the `no-captured-interviews` gate blocks `workers/feedback-agent/evals/{fixtures,runs}/`)
- [ ] No references to the pre-open-source product name outside `NOTICE` and `README.md` (the `debrand` gate checks file contents *and* filenames)

## Config changes

<!-- Delete if none. Otherwise: which .env variables, which services need a
     RECREATE rather than a restart (env_file is read at container create
     time), and whether setup-ui's varmap.py needs the new field. -->

## Anything reviewers should push back on

<!-- Shortcuts taken, assumptions made, things you were unsure about. A PR that
     names its own weak spot gets a better review than one that hides it. -->
