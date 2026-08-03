"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Building2, Plus, LogOut, ClipboardList, Tag, CreditCard, FileText } from "lucide-react";
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
            <Link
              href="/assessments"
              id="nav-assessments"
              className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                isActive("/assessments") ? "bg-secondary font-medium" : "hover:bg-secondary/50"
              }`}
            >
              <ClipboardList className="w-4 h-4" />
              Assessments
            </Link>
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
            <Link
              href="/promotions"
              id="nav-promotions"
              className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                isActive("/promotions") ? "bg-secondary font-medium" : "hover:bg-secondary/50"
              }`}
            >
              <Tag className="w-4 h-4" />
              Promotions
            </Link>
            <Link
              href="/subscriptions"
              id="nav-subscriptions"
              className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                isActive("/subscriptions") ? "bg-secondary font-medium" : "hover:bg-secondary/50"
              }`}
            >
              <CreditCard className="w-4 h-4" />
              Subscriptions
            </Link>
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
