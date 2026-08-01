import { describe, expect, test } from 'bun:test';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const EMOJI_RANGES = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;

function collectFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    const st = statSync(p);
    if (st.isDirectory()) {
      collectFiles(p, out);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry)) continue;
    if (entry.endsWith('.test.ts') || entry.endsWith('.test.tsx')) continue;
    if (entry.endsWith('.fixture.ts')) continue;
    out.push(p);
  }
  return out;
}

describe('no-emoji lint', () => {
  test('src/components contains no emoji characters', () => {
    const files = collectFiles(join(process.cwd(), 'src', 'components'));
    const offenders: string[] = [];
    for (const f of files) {
      const text = readFileSync(f, 'utf8');
      if (EMOJI_RANGES.test(text)) offenders.push(f);
    }
    expect(offenders).toEqual([]);
  });
});
