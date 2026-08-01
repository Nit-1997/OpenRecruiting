import { createServerClient } from '@supabase/ssr';
import { type NextRequest, NextResponse } from 'next/server';

// Server-side session refresh + auth gate for recruiter-app. Reads the SHARED
// `openrecruiting-auth` cookie (set by landing on the common domain), refreshes it,
// and redirects unauthenticated users on protected routes to the landing
// login. Mirrors recruiter-app v1's middleware so the two apps behave identically.

const COOKIE_NAME = 'openrecruiting-auth';
const LANDING_URL = process.env.NEXT_PUBLIC_LANDING_URL || 'http://localhost:3000';

// Public surfaces that must never be auth-gated:
// - feedback + screening portals (own token auth), API route handlers (own
//   header auth), the auth pages themselves.
const PUBLIC_PREFIXES = ['/feedback', '/screening', '/api', '/login', '/verify', '/set-password'];

function isPublic(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Feedback + screening portals + API carry their own auth and don't need a
  // session refresh.
  if (
    pathname.startsWith('/feedback') ||
    pathname.startsWith('/screening') ||
    pathname.startsWith('/api')
  ) {
    return NextResponse.next();
  }

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseKey =
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  // Without Supabase config we can't evaluate the session — fail open rather
  // than locking everyone out.
  if (!supabaseUrl || !supabaseKey) {
    return NextResponse.next();
  }

  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(supabaseUrl, supabaseKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        for (const { name, value } of cookiesToSet) request.cookies.set(name, value);
        supabaseResponse = NextResponse.next({ request });
        for (const { name, value, options } of cookiesToSet) {
          supabaseResponse.cookies.set(name, value, options);
        }
      },
    },
    cookieOptions: {
      name: COOKIE_NAME,
      ...(process.env.NEXT_PUBLIC_COOKIE_DOMAIN
        ? { domain: process.env.NEXT_PUBLIC_COOKIE_DOMAIN }
        : {}),
    },
  });

  // Resolve the user from the (shared) cookie. Fail OPEN on a transient error
  // (network blip validating the JWT) — redirecting on a transient failure can
  // ping-pong with landing's authed→app redirect into a loop. Only redirect
  // when we positively determined there is NO user.
  let user = null;
  try {
    const result = await supabase.auth.getUser();
    user = result.data.user;
  } catch {
    return supabaseResponse;
  }

  if (!user && !isPublic(pathname)) {
    const redirect = encodeURIComponent(pathname);
    return NextResponse.redirect(`${LANDING_URL}/login?redirect=${redirect}`);
  }

  return supabaseResponse;
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)',
  ],
};
