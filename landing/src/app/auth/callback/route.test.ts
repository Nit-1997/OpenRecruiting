import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextResponse } from "next/server";

// Mock supabase server client
const mockSignOut = vi.fn(() => Promise.resolve({ error: null }));
const mockExchangeCodeForSession = vi.fn();
vi.mock("@/lib/supabase/server", () => ({
  createClient: vi.fn(() => Promise.resolve({
    auth: {
      exchangeCodeForSession: mockExchangeCodeForSession,
      signOut: mockSignOut,
    },
  })),
}));

// Mock next/headers cookies()
const mockCookieStore = {
  get: vi.fn(() => undefined),
  delete: vi.fn(),
};
vi.mock("next/headers", () => ({
  cookies: () => Promise.resolve(mockCookieStore),
}));

// Import AFTER mocks
import { GET } from "./route";

const SESSION_FIXTURE = {
  session: {
    access_token: "test-token",
    user: {
      id: "user-1",
      email: "user@test.com",
      app_metadata: { provider: "google" },
      user_metadata: { password_set: true },
    },
  },
};

const ORIGIN = "http://localhost:3000";
const APP_URL = "http://localhost:3005";

function makeRequest(code = "test-code") {
  return new Request(`${ORIGIN}/auth/callback?code=${code}`);
}

describe("auth/callback route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockExchangeCodeForSession.mockResolvedValue({ data: SESSION_FIXTURE, error: null });
    mockCookieStore.get.mockReturnValue(undefined);
    process.env.NEXT_PUBLIC_APP_URL = APP_URL;
    process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000";
    globalThis.fetch = vi.fn();
  });

  it("redirects to /dashboard on a 2xx complete-signup response", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ is_new: false }), { status: 200, headers: { "Content-Type": "application/json" } })
    );

    const res = await GET(makeRequest());

    expect(res).toBeInstanceOf(NextResponse);
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe(`${APP_URL}/dashboard`);
    expect(mockSignOut).not.toHaveBeenCalled();
  });

  it("redirects to /access-denied on a 403 with signup_blocked code", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ detail: { message: "blocked", code: "signup_blocked" } }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      })
    );

    const res = await GET(makeRequest());

    expect(res.headers.get("location")).toBe(`${ORIGIN}/access-denied`);
    expect(mockSignOut).toHaveBeenCalledOnce();
  });

  it("redirects to /login?error=auth_unavailable on a 403 with a different code", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "something_else" } }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      })
    );

    const res = await GET(makeRequest());

    expect(res.headers.get("location")).toBe(`${ORIGIN}/login?error=auth_unavailable`);
    expect(mockSignOut).toHaveBeenCalledOnce();
  });

  it("redirects to /login?error=auth_unavailable on a 500 backend response", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("internal error", { status: 500 })
    );

    const res = await GET(makeRequest());

    expect(res.headers.get("location")).toBe(`${ORIGIN}/login?error=auth_unavailable`);
    expect(mockSignOut).toHaveBeenCalledOnce();
  });

  it("redirects to /login?error=auth_unavailable when fetch throws (timeout/network)", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("AbortError"));

    const res = await GET(makeRequest());

    expect(res.headers.get("location")).toBe(`${ORIGIN}/login?error=auth_unavailable`);
    expect(mockSignOut).toHaveBeenCalledOnce();
  });
});
