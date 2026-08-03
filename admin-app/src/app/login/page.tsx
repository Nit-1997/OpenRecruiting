"use client";

import { useState } from "react";
import { Building2, Lock, Mail, Eye, EyeOff } from "lucide-react";
import { createClient } from "@/lib/supabase/client";

const MAX_LOGIN_ATTEMPTS = 5;
const LOCKOUT_DURATION_MS = 15 * 60 * 1000;

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const checkRateLimit = (): boolean => {
    const attempts = JSON.parse(sessionStorage.getItem("loginAttempts") || "{}");
    const now = Date.now();

    if (attempts.count >= MAX_LOGIN_ATTEMPTS && now - attempts.lastAttempt < LOCKOUT_DURATION_MS) {
      const remainingMs = LOCKOUT_DURATION_MS - (now - attempts.lastAttempt);
      const remainingMins = Math.ceil(remainingMs / 60000);
      setError(`Too many attempts. Try again in ${remainingMins} minute${remainingMins > 1 ? "s" : ""}`);
      return false;
    }

    if (now - attempts.lastAttempt >= LOCKOUT_DURATION_MS) {
      sessionStorage.removeItem("loginAttempts");
    }

    return true;
  };

  const recordFailedAttempt = () => {
    const attempts = JSON.parse(sessionStorage.getItem("loginAttempts") || '{"count": 0}');
    sessionStorage.setItem("loginAttempts", JSON.stringify({
      count: attempts.count + 1,
      lastAttempt: Date.now()
    }));
  };

  const clearAttempts = () => {
    sessionStorage.removeItem("loginAttempts");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!checkRateLimit()) {
      return;
    }

    setIsLoading(true);

    try {
      const supabase = createClient();
      const { data, error: authError } = await supabase.auth.signInWithPassword({
        email: email.trim().toLowerCase(),
        password,
      });

      if (authError) {
        recordFailedAttempt();
        setError("Invalid email or password");
        setIsLoading(false);
        return;
      }

      if (data.session && data.user) {
        const { data: profile, error: profileError } = await supabase
          .from("profiles")
          .select("is_staff")
          .eq("id", data.user.id)
          .maybeSingle();

        if (profileError) {
          await supabase.auth.signOut();
          setError("Unable to verify access. Please contact support.");
          setIsLoading(false);
          return;
        }

        if (!profile) {
          console.error("No profile found for user:", data.user.id);
          await supabase.auth.signOut();
          setError("User profile not found. Please contact support.");
          setIsLoading(false);
          return;
        }

        if (profile.is_staff !== true) {
          await supabase.auth.signOut();
          recordFailedAttempt();
          setError("Access denied. Only staff can access this portal.");
          setIsLoading(false);
          return;
        }

        clearAttempts();
        window.location.href = "/";
      }
    } catch {
      recordFailedAttempt();
      setError("An unexpected error occurred");
      setIsLoading(false);
    }
  };

  return (
    <div id="login-page" className="min-h-screen bg-secondary/30 flex items-center justify-center p-4">
      <div id="login-container" className="w-full max-w-md">
        <div id="login-header" className="text-center mb-8">
          <div className="flex items-center justify-center gap-3 mb-4">
            <Building2 className="w-12 h-12 text-primary" />
          </div>
          <h1 id="login-title" className="text-3xl font-bold">OpenRecruiting Admin</h1>
          <p id="login-subtitle" className="text-muted-foreground mt-2">Sign in to access the admin dashboard</p>
        </div>

        <div id="login-card" className="bg-card rounded-2xl border border-border p-8 shadow-lg">
          <form id="login-form" onSubmit={handleSubmit} className="space-y-6">
            <div id="email-field">
              <label htmlFor="email-input" className="block text-sm font-medium mb-2">
                Email
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                <input
                  id="email-input"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="Enter email"
                  className="w-full pl-11 pr-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                  required
                  autoComplete="email"
                />
              </div>
            </div>

            <div id="password-field">
              <label htmlFor="password-input" className="block text-sm font-medium mb-2">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                <input
                  id="password-input"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter password"
                  className="w-full pl-11 pr-12 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                  required
                  autoComplete="current-password"
                />
                <button
                  id="toggle-password-btn"
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>
            </div>

            {error && (
              <div id="error-message" className="p-3 bg-destructive/10 text-destructive text-sm rounded-lg">
                {error}
              </div>
            )}

            <button
              id="login-btn"
              type="submit"
              disabled={isLoading || !email || !password}
              className="w-full py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
            >
              {isLoading ? "Signing in..." : "Sign In"}
            </button>
          </form>
        </div>

        <p id="login-footer" className="text-center text-sm text-muted-foreground mt-6">
          Customer onboarding and requisition management
        </p>
      </div>
    </div>
  );
}
