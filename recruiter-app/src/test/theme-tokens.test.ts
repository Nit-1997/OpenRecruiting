import { describe, expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Source-level guard for the Tailwind v4 @theme bridge (FE-F1).
 *
 * In Tailwind v4 a utility like `bg-popover` emits NO CSS unless a matching
 * `--color-popover` theme token exists — it fails silently. The ui/* component
 * kit references the tokens below; if any is dropped from the @theme block the
 * corresponding utility goes dead with no build error. This test reads the
 * SOURCE @theme block and asserts each required token is declared, so a
 * regression is caught at unit-test time rather than in the rendered UI.
 */

const GLOBALS_CSS = readFileSync(join(process.cwd(), 'src', 'app', 'globals.css'), 'utf8');

function extractThemeBlock(css: string): string {
  const start = css.indexOf('@theme');
  if (start === -1) throw new Error('@theme block not found in globals.css');
  const open = css.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < css.length; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}') {
      depth--;
      if (depth === 0) return css.slice(open + 1, i);
    }
  }
  throw new Error('Unterminated @theme block in globals.css');
}

const THEME_BLOCK = extractThemeBlock(GLOBALS_CSS);

// Every token the ui/* kit and feedback/login pages reference. Each must be
// declared in the @theme block or its Tailwind utility silently emits nothing.
const REQUIRED_TOKENS = [
  // ui/* kit palette aliases
  '--color-canvas',
  '--color-tile',
  '--color-charcoal',
  '--color-border-strong',
  '--color-accent-agent',
  // shadcn-style semantic aliases (dialog / popover / tooltip / textarea)
  '--color-popover',
  '--color-popover-foreground',
  '--color-foreground',
  '--color-background',
  '--color-muted',
  '--color-muted-foreground',
  '--color-input',
  '--color-ring',
  '--color-destructive',
  // radii + shadow
  '--radius-input',
  '--radius-card-lg',
  '--shadow-card',
] as const;

describe('Tailwind @theme token bridge', () => {
  for (const token of REQUIRED_TOKENS) {
    test(`@theme declares ${token}`, () => {
      const declared = new RegExp(`(^|\\n)\\s*${token}\\s*:`).test(THEME_BLOCK);
      expect(declared).toBe(true);
    });
  }
});
