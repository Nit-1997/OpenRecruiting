import { describe, expect, it } from 'bun:test';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const SRC = join(import.meta.dir, '..', '..');

/** Server-side files legitimately read live process.env — a Node server runs at
 *  request time (output: 'standalone'), so these are NOT baked into the client
 *  bundle and a container restart applies them. */
const SERVER_SIDE_ALLOWED = [
  'middleware.ts',
  'lib/supabase-server.ts',
  'app/api/deepgram/route.ts',
  'lib/runtime-config.ts',
  // Not server-side, but not runtime config either: these two read env only in
  // a Node test process, where process.env IS live. Kept deliberately narrow —
  // lib/test-flags.ts exists precisely so lib/env.ts, which holds the real
  // settings, needs no entry here.
  'lib/test-flags.ts',
  'test-setup.ts',
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
    // time. Any client module reading it holds a value a container restart
    // cannot change — the failure that makes a correct .env look broken, with
    // no error anywhere to explain it. Client code reads getRuntimeConfig()
    // instead; see src/lib/runtime-config.ts.
    const offenders = walk(SRC)
      .filter((f) => !SERVER_SIDE_ALLOWED.some((a) => f.endsWith(a)))
      .filter((f) => !f.includes('/test/'))
      .filter((f) => readFileSync(f, 'utf8').includes('process.env.NEXT_PUBLIC_'))
      .map((f) => f.slice(SRC.length + 1));

    expect(offenders).toEqual([]);
  });
});
