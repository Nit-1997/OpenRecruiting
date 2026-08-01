import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock supabase server client BEFORE importing the route module
const mockGetSession = vi.fn();
vi.mock("@/lib/supabase/server", () => ({
  createClient: vi.fn(() =>
    Promise.resolve({
      auth: { getSession: mockGetSession },
    }),
  ),
}));

// Import AFTER mocks
import { POST } from "./route";

const API_URL = "http://localhost:8000";
const REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback";

function makeForm(overrides: Record<string, string> = {}) {
  const fd = new FormData();
  const defaults: Record<string, string> = {
    decision: "allow",
    client_id: "mcp_test_client",
    redirect_uri: REDIRECT_URI,
    code_challenge: "x".repeat(43),
    code_challenge_method: "S256",
    scope: "cortex:read",
    audience: "cortex-mcp",
    state: "abc",
  };
  for (const [k, v] of Object.entries({ ...defaults, ...overrides })) {
    fd.set(k, v);
  }
  return fd;
}

function makeRequest(form: FormData): Request {
  return new Request("http://localhost:3000/oauth/consent/submit", {
    method: "POST",
    body: form,
  });
}

describe("/oauth/consent/submit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.NEXT_PUBLIC_API_V2_URL = API_URL;
    mockGetSession.mockResolvedValue({
      data: { session: { access_token: "supabase-jwt-here" } },
    });
    globalThis.fetch = vi.fn();
  });

  it("returns 401 if there is no session", async () => {
    mockGetSession.mockResolvedValue({ data: { session: null } });
    const res = await POST(makeRequest(makeForm()));
    expect(res.status).toBe(401);
    expect((globalThis.fetch as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled();
  });

  it("returns 400 when required fields are missing", async () => {
    const fd = makeForm();
    fd.delete("client_id");
    const res = await POST(makeRequest(fd));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toContain("client_id");
  });

  it("forwards form to backend with Authorization header and returns the 302 location", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(null, {
        status: 302,
        headers: { Location: `${REDIRECT_URI}?code=abc123&state=abc` },
      }),
    );

    const res = await POST(makeRequest(makeForm()));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.redirect_url).toBe(`${REDIRECT_URI}?code=abc123&state=abc`);

    const call = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe(`${API_URL}/api/v2/mcp/oauth/authorize/decision`);
    expect(call[1].method).toBe("POST");
    expect(call[1].headers.Authorization).toBe("Bearer supabase-jwt-here");
    expect(call[1].redirect).toBe("manual");
    const sentBody = new URLSearchParams(call[1].body as string);
    expect(sentBody.get("decision")).toBe("allow");
    expect(sentBody.get("client_id")).toBe("mcp_test_client");
    expect(sentBody.get("state")).toBe("abc");
  });

  it("propagates the user's decision to deny", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(null, {
        status: 302,
        headers: { Location: `${REDIRECT_URI}?error=access_denied&state=abc` },
      }),
    );
    const res = await POST(makeRequest(makeForm({ decision: "deny" })));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.redirect_url).toContain("error=access_denied");

    const sentBody = new URLSearchParams(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body as string,
    );
    expect(sentBody.get("decision")).toBe("deny");
  });

  it("returns 502 when the backend redirect lacks a Location header", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(null, { status: 302 }),
    );
    const res = await POST(makeRequest(makeForm()));
    expect(res.status).toBe(502);
    expect((await res.json()).error).toMatch(/redirect without a target/);
  });

  it("surfaces backend OAuth error envelopes as 400", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(
        JSON.stringify({ error: "invalid_grant", error_description: "code expired" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      ),
    );
    const res = await POST(makeRequest(makeForm()));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("code expired");
  });

  it("returns 502 if the backend is unreachable", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new TypeError("fetch failed"));
    const res = await POST(makeRequest(makeForm()));
    expect(res.status).toBe(502);
    expect((await res.json()).error).toContain("authorization server");
  });
});
