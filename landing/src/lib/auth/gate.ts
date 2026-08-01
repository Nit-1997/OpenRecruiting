import type { SupabaseClient } from "@supabase/supabase-js";

const COOKIE_NAME = "openrecruiting-auth";

/**
 * Manually expire the auth cookie. Belt-and-suspenders fallback when supabase.auth.signOut()
 * fails for any reason — without this, a failed signOut could leave a valid session cookie
 * attached to a fail-closed redirect response.
 *
 * The domain attribute mirrors the setter in `lib/supabase/client.ts` and `lib/supabase/server.ts`.
 * If you change the cookie domain in those files, update this one too. Note: when the auth
 * token exceeds ~4KB, @supabase/ssr chunks it into `openrecruiting-auth.0`/`.1`; signOut() handles
 * those primarily, this fallback only clears the unchunked name.
 */
function clearAuthCookie(): void {
  if (typeof document === "undefined") return;
  const cookieDomain = process.env.NEXT_PUBLIC_COOKIE_DOMAIN;
  const domainAttr = cookieDomain ? `; domain=${cookieDomain}` : "";
  document.cookie = `${COOKIE_NAME}=; path=/${domainAttr}; max-age=0; SameSite=Lax`;
}

interface GateAndRedirectArgs {
  supabase: SupabaseClient;
  accessToken: string;
  target: string;
}

/**
 * Call the backend invite-only gate (`/api/v2/auth/complete-signup`). On 2xx, navigate
 * to `target`. On any other outcome (403 with signup_blocked code, other 403, other non-2xx,
 * fetch throw, timeout), sign the user out, clear the cookie, and redirect to the appropriate
 * fail-closed destination:
 *   - 403 + body.detail.code === "signup_blocked" → /access-denied
 *   - everything else → /login?error=auth_unavailable
 *
 * This function always navigates (sets `window.location.href`) and never returns a value.
 * Callers should not perform their own redirect after calling it.
 *
 * Uses a named-args object so callers can't accidentally swap `accessToken` and `target` —
 * both are strings and TypeScript would not catch a positional swap.
 */
export async function gateAndRedirect({
  supabase,
  accessToken,
  target,
}: GateAndRedirectArgs): Promise<void> {
  const apiUrl = process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8000";

  const failClosed = async (errorTarget: string) => {
    try {
      await supabase.auth.signOut();
    } catch (e) {
      console.error("signOut failed before fail-closed redirect:", e);
    }
    try {
      clearAuthCookie();
    } catch (e) {
      console.error("clearAuthCookie failed before fail-closed redirect:", e);
    }
    window.location.href = errorTarget;
  };

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  let res: Response;
  try {
    res = await fetch(`${apiUrl}/api/v2/auth/complete-signup`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      signal: controller.signal,
    });
  } catch (e) {
    console.error("complete-signup fetch failed:", e);
    await failClosed("/login?error=auth_unavailable");
    return;
  } finally {
    clearTimeout(timeout);
  }

  if (res.status === 403) {
    const body = (await res.json().catch(() => null)) as { detail?: { code?: string } } | null;
    if (body?.detail?.code === "signup_blocked") {
      await failClosed("/access-denied");
      return;
    }
    console.error("complete-signup unexpected 403:", body);
    await failClosed("/login?error=auth_unavailable");
    return;
  }

  if (!res.ok) {
    console.error("complete-signup non-ok response:", res.status);
    await failClosed("/login?error=auth_unavailable");
    return;
  }

  // 2xx — gate accepted; proceed to the intended target.
  window.location.href = target;
}
