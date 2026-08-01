# OpenRecruiting v2

The agentic recruiting workspace. A three-pane app — navigation rail, chat
(text + voice), and a live workspace of artifacts that the AI agent builds
and the user edits together.

This repo contains the **frontend** for OpenRecruiting v2 (UI-only; assumes a separate
backend service emits the agent event stream defined in the spec).

## Quick start

Requirements: [Bun](https://bun.sh) 1.1+.

```bash
bun install
cp .env.example .env.local   # fill in real values
bun dev                      # http://localhost:3000
```

## Common scripts

| Script | What it does |
|---|---|
| `bun dev` | Start the Next.js dev server |
| `bun run build` | Production build |
| `bun run start` | Run the production build locally |
| `bun run lint` | Biome lint + format check |
| `bun run lint:fix` | Biome auto-fix |
| `bun run typecheck` | `tsc --noEmit` |
| `bun run test` | Unit tests (Bun test) |
| `bun run e2e` | Playwright E2E tests |
| `bun run e2e:ui` | Playwright in UI mode (debug) |

## Documentation

- **Spec:** `docs/superpowers/specs/2026-04-17-slice1-agentic-shell-design.md`
- **Plans:** `docs/superpowers/plans/`
- **Contributing:** `CONTRIBUTING.md`

## Directory layout

See `src/**/README.md` — each top-level bucket documents what lives there and
what doesn't.
