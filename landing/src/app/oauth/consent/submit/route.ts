import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

// Read at CALL time, not module load. This is a server route handler, so
// process.env is live — but a module-level const captures whatever was set when
// the module was first imported, which meant the env var was effectively
// ignored and the fallback below always won. Its test set the var and then
// asserted the fallback value, so it passed for the wrong reason and proved
// nothing; the two only agreed because the fallback was also wrong (:8000,
// while the backend listens on :8004).
function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8004";
}

const REQUIRED_FIELDS = [
  "decision",
  "client_id",
  "redirect_uri",
  "code_challenge",
  "code_challenge_method",
  "scope",
  "audience",
] as const;

/**
 * Submit handler for the MCP consent screen.
 *
 * Flow:
 *   1. Read the user's Supabase session server-side (via landing's
 *      cookie). Reject if no session — the consent page should not be
 *      reachable without one, but be defensive.
 *   2. Forward the form fields to backend's authorize/decision
 *      endpoint with Authorization: Bearer <access_token>. The backend
 *      issues the auth code and returns a 302 redirect to the OAuth client
 *      (e.g. claude.ai).
 *   3. Pluck the Location header off the 302 and hand it back to the
 *      client component as JSON. The client then navigates the browser.
 *
 * We deliberately do not let the browser follow the 302 itself — fetch
 * inside a client component does not propagate cross-origin redirects, and
 * a full form POST cross-site cannot carry our session header without
 * SameSite=None cookies. The route-handler bridge is the cleanest path.
 */
export async function POST(request: Request): Promise<NextResponse> {
  const form = await request.formData();

  // Validate required fields.
  for (const k of REQUIRED_FIELDS) {
    if (!form.get(k)) {
      return NextResponse.json(
        { error: `Missing required field: ${k}` },
        { status: 400 },
      );
    }
  }

  // Resolve session — server-side, via openrecruiting-auth cookie.
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) {
    return NextResponse.json(
      { error: "Your session has expired. Please sign in again." },
      { status: 401 },
    );
  }

  // Build the form body to forward.
  const forwardBody = new URLSearchParams();
  for (const k of REQUIRED_FIELDS) {
    forwardBody.set(k, String(form.get(k)));
  }
  const stateVal = form.get("state");
  if (stateVal) forwardBody.set("state", String(stateVal));

  let backendResp: Response;
  try {
    backendResp = await fetch(`${apiBase()}/api/v2/mcp/oauth/authorize/decision`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${session.access_token}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: forwardBody.toString(),
      redirect: "manual",
    });
  } catch (e) {
    return NextResponse.json(
      {
        error: `Could not reach the authorization server: ${
          e instanceof Error ? e.message : "network error"
        }`,
      },
      { status: 502 },
    );
  }

  console.log("[consent/submit] backend response", {
    status: backendResp.status,
    location: backendResp.headers.get("location"),
  });

  // Happy path: 302 with a Location header pointing back to the MCP client.
  if (backendResp.status === 302) {
    const location = backendResp.headers.get("location");
    if (!location) {
      return NextResponse.json(
        { error: "Authorization server returned a redirect without a target." },
        { status: 502 },
      );
    }
    return NextResponse.json({ redirect_url: location });
  }

  // Backend returned a structured OAuth error. Surface it.
  let body: { error?: string; error_description?: string; detail?: string } = {};
  try {
    body = await backendResp.json();
  } catch {
    // Non-JSON error body — keep the empty object.
  }
  return NextResponse.json(
    {
      error:
        body.error_description ||
        body.detail ||
        body.error ||
        `Authorization failed (HTTP ${backendResp.status})`,
    },
    { status: backendResp.status >= 500 ? 502 : 400 },
  );
}
