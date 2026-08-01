# Contributing to OpenRecruiting v2

## Quality bar (non-negotiable)

Before a line of code ships:

1. **Modular, reusable.** Each file has one clear purpose. Files growing past
   ~250 lines or doing more than one thing get split.
2. **DRY.** Before writing anything, check for an existing util/hook/component.
   Three occurrences of a pattern becomes an abstraction.
3. **Readable over clever.** Obvious names, straightforward control flow. No
   one-liner acrobatics.
4. **YAGNI.** No speculative abstractions. No "just in case" branches.
5. **Type-safe.** TypeScript strict mode. No `any`. No `@ts-ignore` without a
   comment explaining why and linking an issue.
6. **Linted.** Biome passes before every commit. Pre-commit hooks enforce.
7. **Tested.** Unit tests for utils, hooks, stores, and JSON Patch logic.
   E2E tests for happy paths and critical edge cases.
8. **No cheap tricks.** No stray `console.log`, no `// TODO` without a tracked
   task, no commented-out code, no magic numbers without named constants.

## Branching and commits

- Feature branches off `main`: `feat/<short-desc>`, `fix/<short-desc>`,
  `chore/<short-desc>`.
- **Conventional commits** are required: `feat:`, `fix:`, `docs:`, `test:`,
  `refactor:`, `chore:`, `ci:`, `style:`, `perf:`.
- Pre-commit hooks (Lefthook) run Biome, typecheck, and related unit tests.
- Pre-push hook runs the full build.
- CI runs lint, typecheck, unit tests, build, and E2E smoke on every PR.

## Testing

- **Unit tests** live next to the code they test: `foo.ts` + `foo.test.ts`.
  Runner: `bun test`.
- **E2E tests** live in `src/test/e2e/` with `*.e2e.ts` suffix. Runner: Playwright.
- New components/utils without tests do not merge. Full stop.

## Editor setup

- Install the [Biome VSCode extension](https://marketplace.visualstudio.com/items?itemName=biomejs.biome).
- Enable format-on-save with Biome as the default formatter.

## Running a single test

```bash
bun test src/lib/patch/patch.test.ts
bunx playwright test src/test/e2e/smoke.e2e.ts
```

## HTML element IDs

Every HTML element in the project gets a unique `id` attribute. This is a
project-wide rule (see the user's global CLAUDE.md). When adding JSX, give
elements meaningful IDs (`id="home-main"`, `id="home-cta"`, etc.).

## Questions?

Start in `docs/superpowers/specs/` for the design. Plans for each phase are
in `docs/superpowers/plans/`.
