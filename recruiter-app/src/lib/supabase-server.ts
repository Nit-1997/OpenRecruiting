import { createServerClient } from '@supabase/ssr';
import type { User } from '@supabase/supabase-js';
import type { NextRequest } from 'next/server';

const COOKIE_NAME = 'openrecruiting-auth';

// Resolve the recruiter from the shared `openrecruiting-auth` cookie (set by landing).
// Mirrors the server-client construction in src/middleware.ts. Returns null when
// Supabase is unconfigured or there is no valid session — callers decide the status.
export async function getRecruiterUserFromRequest(request: NextRequest): Promise<User | null> {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key =
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return null;

  const supabase = createServerClient(url, key, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll() {
        // Validation-only: this route does not write a refreshed cookie back.
      },
    },
    cookieOptions: {
      name: COOKIE_NAME,
      ...(process.env.NEXT_PUBLIC_COOKIE_DOMAIN
        ? { domain: process.env.NEXT_PUBLIC_COOKIE_DOMAIN }
        : {}),
    },
  });

  try {
    const { data } = await supabase.auth.getUser();
    return data.user;
  } catch {
    return null;
  }
}
