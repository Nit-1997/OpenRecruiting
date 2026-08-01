import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";
import { gateAndRedirect } from "./gate";

const mockSignOut = vi.fn();

const supabaseStub = {
  auth: {
    signOut: mockSignOut,
  },
} as unknown as SupabaseClient;

const APP_URL = "http://localhost:3005";
const TARGET = `${APP_URL}/dashboard`;
const ACCESS_TOKEN = "test-token";

let locationMock: { href: string };

describe("gateAndRedirect", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSignOut.mockResolvedValue({ error: null });

    locationMock = { href: "" };
    Object.defineProperty(window, "location", {
      value: locationMock,
      writable: true,
      configurable: true,
    });

    process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000";
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    document.cookie = "openrecruiting-auth=; path=/; max-age=0";
  });

  it("redirects to target on 2xx; does not call signOut", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ is_new: false }), { status: 200 }),
    );

    await gateAndRedirect({ supabase: supabaseStub, accessToken: ACCESS_TOKEN, target: TARGET });

    expect(locationMock.href).toBe(TARGET);
    expect(mockSignOut).not.toHaveBeenCalled();
  });

  it("redirects to /access-denied on 403 with signup_blocked code; signs out", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "signup_blocked", message: "blocked" } }), { status: 403 }),
    );

    await gateAndRedirect({ supabase: supabaseStub, accessToken: ACCESS_TOKEN, target: TARGET });

    expect(locationMock.href).toBe("/access-denied");
    expect(mockSignOut).toHaveBeenCalledOnce();
  });

  it("redirects to /login?error=auth_unavailable on 403 with other code; signs out", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "something_else" } }), { status: 403 }),
    );

    await gateAndRedirect({ supabase: supabaseStub, accessToken: ACCESS_TOKEN, target: TARGET });

    expect(locationMock.href).toBe("/login?error=auth_unavailable");
    expect(mockSignOut).toHaveBeenCalledOnce();
  });

  it("redirects to /login?error=auth_unavailable on 500; signs out", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("internal error", { status: 500 }),
    );

    await gateAndRedirect({ supabase: supabaseStub, accessToken: ACCESS_TOKEN, target: TARGET });

    expect(locationMock.href).toBe("/login?error=auth_unavailable");
    expect(mockSignOut).toHaveBeenCalledOnce();
  });

  it("redirects to /login?error=auth_unavailable when fetch rejects (network/timeout); signs out", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("AbortError"));

    await gateAndRedirect({ supabase: supabaseStub, accessToken: ACCESS_TOKEN, target: TARGET });

    expect(locationMock.href).toBe("/login?error=auth_unavailable");
    expect(mockSignOut).toHaveBeenCalledOnce();
  });

  it("still navigates to fail-closed target when signOut throws", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "signup_blocked" } }), { status: 403 }),
    );
    mockSignOut.mockRejectedValue(new Error("network down"));

    await gateAndRedirect({ supabase: supabaseStub, accessToken: ACCESS_TOKEN, target: TARGET });

    // Must still redirect even if signOut threw
    expect(locationMock.href).toBe("/access-denied");
  });

  it("clears the openrecruiting-auth cookie on fail-closed paths", async () => {
    document.cookie = "openrecruiting-auth=test-value; path=/";
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "signup_blocked" } }), { status: 403 }),
    );

    await gateAndRedirect({ supabase: supabaseStub, accessToken: ACCESS_TOKEN, target: TARGET });

    // After clearAuthCookie runs with max-age=0, the cookie should not be retrievable.
    expect(document.cookie).not.toContain("openrecruiting-auth=test-value");
  });
});
