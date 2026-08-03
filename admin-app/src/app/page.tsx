"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AuthGuard } from "@/components/auth-guard";

export default function AdminDashboard() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/customers");
  }, [router]);

  return (
    <AuthGuard>
      <div id="admin-dashboard" className="min-h-screen bg-secondary/30 flex items-center justify-center">
        <p className="text-muted-foreground">Redirecting...</p>
      </div>
    </AuthGuard>
  );
}
