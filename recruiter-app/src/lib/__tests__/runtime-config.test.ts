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
