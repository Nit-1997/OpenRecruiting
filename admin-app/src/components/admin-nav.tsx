"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Building2, Plus, LogOut, FileText } from "lucide-react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { createClient } from "@/lib/supabase/client";

export function AdminNav() {
  const pathname = usePathname();
  const router = useRouter();

  const handleLogout = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
  };

  const isActive = (path: string) => pathname.startsWith(path);

  return (
    <nav id="admin-nav" className="bg-card border-b border-border">
      <div className="px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-8">
          <Link href="/customers" className="flex items-center gap-3">
            <Building2 className="w-8 h-8 text-primary" />
            <span className="text-xl font-bold">OpenRecruiting Admin</span>
          </Link>
          <div className="flex items-center gap-1">
            <Link
              href="/customers"
              id="nav-organizations"
              className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                isActive("/customers") ? "bg-secondary font-medium" : "hover:bg-secondary/50"
              }`}
            >
              <Building2 className="w-4 h-4" />
              Organizations
            </Link>
            {/* Assessments is parked: the templates API and the /assessments
                routes still work, but there is no candidate-facing app to take
                an assessment in, so the entry point stays hidden. */}
            <Link
              href="/blog"
              id="nav-blog"
              className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                isActive("/blog") ? "bg-secondary font-medium" : "hover:bg-secondary/50"
              }`}
            >
              <FileText className="w-4 h-4" />
              Blog
            </Link>
            {/* Promotions and Subscriptions are gone: there are no plans and no
                payment provider. An org's credit budget is edited on its own
                page, under Organizations. */}
          </div>
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/customers/new"
            id="nav-new-organization"
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Organization
          </Link>
          <ThemeToggle />
          <button
            id="logout-btn"
            onClick={handleLogout}
            className="flex items-center gap-2 px-4 py-2 text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Logout
          </button>
        </div>
      </div>
    </nav>
  );
}
