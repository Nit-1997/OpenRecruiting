import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

/**
 * Genuinely server-only modules. These run on the Node server at request time,
 * so process.env is live for them and a container restart already applies a
 * change — they are NOT compiled into the client bundle.
 *
 * Note "no 'use client' directive" is NOT the test for membership here: a module
 * without the directive still ships to the browser if a client component
 * imports it. lib/auth/gate.ts and lib/supabase/client.ts are both in that
 * category and were converted rather than allowlisted.
 */
const SERVER_SIDE_ALLOWED = [
  'middleware.ts',
  'lib/supabase/server.ts',
  'lib/blog-api.ts',
  'lib/runtime-config.ts',
  'app/auth/callback/route.ts',
  'app/oauth/consent/page.tsx',
  'app/oauth/consent/submit/route.ts',
  'app/sitemap.ts',
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
  it('is not read by any client-bundled module', () => {
    // Next.js inlines these into the client bundle at BUILD time, so any
    // client-bundled reader holds a value a container restart cannot change —
    // the failure that makes a correct .env look broken with no error to
    // explain it. Client code reads getRuntimeConfig() instead.
    const offenders = walk(SRC)
      .filter((f) => !SERVER_SIDE_ALLOWED.some((a) => f.endsWith(a)))
      .filter((f) => readFileSync(f, 'utf8').includes('process.env.NEXT_PUBLIC_'))
      .map((f) => f.slice(SRC.length + 1));

    expect(offenders).toEqual([]);
  });
});
