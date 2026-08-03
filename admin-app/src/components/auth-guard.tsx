"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [isAuthed, setIsAuthed] = useState<boolean | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);

  const checkAuth = useCallback(async () => {
    const supabase = createClient();

    try {
      const { data: { user }, error } = await supabase.auth.getUser();

      if (error) {
        console.error("Auth error:", error.message);
        setIsAuthed(false);
        setIsLoading(false);
        if (pathname !== "/login") {
          router.push("/login");
        }
        return;
      }

      if (user) {
        const { data: profile, error: profileError } = await supabase
          .from("profiles")
          .select("is_staff")
          .eq("id", user.id)
          .single();

        if (profileError || !profile?.is_staff) {
          console.error("Access denied: User is not staff");
          setAccessDenied(true);
          setIsAuthed(false);
          await supabase.auth.signOut();
          setIsLoading(false);
          return;
        }

        setIsAuthed(true);
      } else {
        setIsAuthed(false);
        if (pathname !== "/login") {
          router.push("/login");
        }
      }
    } catch (err) {
      console.error("Auth check failed:", err);
      setIsAuthed(false);
      if (pathname !== "/login") {
        router.push("/login");
      }
    } finally {
      setIsLoading(false);
    }
  }, [pathname, router]);

  useEffect(() => {
    const supabase = createClient();

    checkAuth();

    const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, session) => {
      if (event === "SIGNED_IN" || event === "TOKEN_REFRESHED") {
        checkAuth();
      } else if (event === "SIGNED_OUT") {
        setIsAuthed(false);
        setIsLoading(false);
        if (pathname !== "/login") {
          router.push("/login");
        }
      } else if (session) {
        checkAuth();
      }
    });

    return () => subscription.unsubscribe();
  }, [checkAuth, pathname, router]);

  if (isLoading) {
    return (
      <div id="auth-loading" className="min-h-screen bg-secondary/30 flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  if (accessDenied) {
    return (
      <div id="access-denied" className="min-h-screen bg-secondary/30 flex items-center justify-center">
        <div id="access-denied-card" className="text-center max-w-md p-8 bg-white dark:bg-background rounded-2xl border border-border shadow-lg">
          <div id="access-denied-icon" className="w-16 h-16 mx-auto mb-4 rounded-full bg-red-100 dark:bg-red-950 flex items-center justify-center">
            <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h2 id="access-denied-title" className="text-xl font-bold mb-2">Access Denied</h2>
          <p id="access-denied-message" className="text-muted-foreground mb-6">
            You do not have permission to access the admin portal. Only staff members can access this area.
          </p>
          <button
            id="access-denied-login-btn"
            onClick={() => {
              setAccessDenied(false);
              router.push("/login");
            }}
            className="px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
          >
            Back to Login
          </button>
        </div>
      </div>
    );
  }

  if (!isAuthed && pathname !== "/login") {
    return null;
  }

  return <>{children}</>;
}
