import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor, screen, fireEvent } from "@testing-library/react";

const mockPush = vi.fn();
const mockGetUser = vi.fn();
const mockGetSession = vi.fn();
const mockSetSession = vi.fn();
const mockSignInWithOAuth = vi.fn();
const mockSignInWithPassword = vi.fn();
const mockSignOut = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => ({
    get: () => null,
  }),
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: {
      getUser: mockGetUser,
      getSession: mockGetSession,
      setSession: mockSetSession,
      signInWithOAuth: mockSignInWithOAuth,
      signInWithPassword: mockSignInWithPassword,
      signOut: mockSignOut,
    },
  }),
}));

vi.mock("@/hooks/useAnalytics", () => ({
  useAnalytics: () => ({ trackEvent: vi.fn() }),
}));

vi.mock("@/components/ui/header", () => ({
  Header: () => <div id="mock-header">Header</div>,
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({ children, ...props }: React.ComponentProps<"button">) => (
    <button {...props}>{children}</button>
  ),
}));

vi.mock("@/components/ui/input", () => ({
  Input: (props: React.ComponentProps<"input">) => <input {...props} />,
}));

const originalLocation = window.location;
const locationMock: { href: string; hash: string; origin: string } = {
  href: "",
  hash: "",
  origin: "http://localhost:3000",
};

beforeEach(() => {
  vi.restoreAllMocks();
  mockPush.mockClear();
  mockGetUser.mockReset();
  mockGetSession.mockReset();
  mockSetSession.mockReset();
  mockSignInWithOAuth.mockReset();
  mockSignInWithPassword.mockReset();
  mockSignOut.mockReset();
  mockSignOut.mockResolvedValue({ error: null });

  locationMock.href = "";
  locationMock.hash = "";
  locationMock.origin = "http://localhost:3000";
  Object.defineProperty(window, "location", {
    writable: true,
    configurable: true,
    value: { ...originalLocation, ...locationMock,
      get href() { return locationMock.href; },
      set href(v: string) { locationMock.href = v; },
    },
  });
  Object.defineProperty(window, "history", {
    writable: true,
    value: { ...window.history, replaceState: vi.fn() },
  });

  // Default getSession: no session (override per-test as needed).
  mockGetSession.mockResolvedValue({ data: { session: null }, error: null });
  // Default fetch — individual tests override.
  global.fetch = vi.fn() as unknown as typeof fetch;
});

const okGateFetch = () =>
  Promise.resolve({
    ok: true,
    status: 200,
    json: async () => ({ ok: true }),
  } as unknown as Response);

describe("Login page redirect logic", () => {
  it("Google OAuth user (no password_set) redirects to dashboard, NOT set-password", async () => {
    mockGetUser.mockResolvedValue({
      data: {
        user: {
          id: "user-1",
          email: "test@gmail.com",
          app_metadata: { provider: "google" },
          user_metadata: { full_name: "Test User" },
        },
      },
      error: null,
    });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: "tok-1",
          user: {
            id: "user-1",
            app_metadata: { provider: "google" },
            user_metadata: { full_name: "Test User" },
          },
        },
      },
      error: null,
    });
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(okGateFetch);

    const LoginPage = (await import("./page")).default;
    render(<LoginPage />);

    await waitFor(() => {
      expect(window.location.href).toContain("/dashboard");
    });

    expect(mockPush).not.toHaveBeenCalledWith("/set-password");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v2/auth/complete-signup"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer tok-1" }),
      }),
    );
  });

  it("email user without password_set redirects to set-password", async () => {
    mockGetUser.mockResolvedValue({
      data: {
        user: {
          id: "user-2",
          email: "test@example.com",
          app_metadata: { provider: "email" },
          user_metadata: {},
        },
      },
      error: null,
    });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: "tok-2",
          user: {
            id: "user-2",
            app_metadata: { provider: "email" },
            user_metadata: {},
          },
        },
      },
      error: null,
    });

    const LoginPage = (await import("./page")).default;
    render(<LoginPage />);

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/set-password");
    });

    // /set-password is invite-driven — gate must NOT be called.
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("email user with password_set redirects to dashboard", async () => {
    mockGetUser.mockResolvedValue({
      data: {
        user: {
          id: "user-3",
          email: "test@example.com",
          app_metadata: { provider: "email" },
          user_metadata: { password_set: true },
        },
      },
      error: null,
    });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: "tok-3",
          user: {
            id: "user-3",
            app_metadata: { provider: "email" },
            user_metadata: { password_set: true },
          },
        },
      },
      error: null,
    });
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(okGateFetch);

    const LoginPage = (await import("./page")).default;
    render(<LoginPage />);

    await waitFor(() => {
      expect(window.location.href).toContain("/dashboard");
    });

    expect(mockPush).not.toHaveBeenCalledWith("/set-password");
  });

  it("no user shows login form", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: null },
      error: null,
    });

    const LoginPage = (await import("./page")).default;
    const { container } = render(<LoginPage />);

    await waitFor(() => {
      expect(container.querySelector("#login-form")).toBeInTheDocument();
    });
  });
});

describe("Login page password sign-in (page integration)", () => {
  const fillAndSubmit = async () => {
    const LoginPage = (await import("./page")).default;
    const { container } = render(<LoginPage />);

    await waitFor(() => {
      expect(container.querySelector("#login-form")).toBeInTheDocument();
    });

    const emailInput = container.querySelector("#login-email") as HTMLInputElement;
    const passwordInput = container.querySelector("#login-password") as HTMLInputElement;
    fireEvent.change(emailInput, { target: { value: "user@example.com" } });
    fireEvent.change(passwordInput, { target: { value: "secret123" } });

    const form = container.querySelector("#login-form") as HTMLFormElement;
    fireEvent.submit(form);
  };

  beforeEach(() => {
    // No pre-existing session — show the form.
    mockGetUser.mockResolvedValue({ data: { user: null }, error: null });
    // Successful password sign-in by default.
    mockSignInWithPassword.mockResolvedValue({ data: {}, error: null });
  });

  // Gate branch behavior (200 / 403 signup_blocked / 500 / fetch throws) is covered
  // exhaustively in src/lib/auth/gate.test.ts. Only the page-level integration that
  // can't be exercised at the helper level lives here.

  it("shows error and does not redirect when no session is created post-signin", async () => {
    mockGetSession.mockResolvedValue({ data: { session: null }, error: null });

    await fillAndSubmit();

    await waitFor(() => {
      expect(screen.getByText(/no session was created/i)).toBeInTheDocument();
    });
    expect(global.fetch).not.toHaveBeenCalled();
    expect(window.location.href).toBe("");
  });
});
