"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Plus, Building2, Search, Archive, RotateCcw, Trash2, AlertTriangle, X, Loader2 } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { getRuntimeConfig } from "@/lib/runtime-config";


// V2 backend base — admin endpoints ported to /api/v2/admin.

const API_V2_URL = getRuntimeConfig().apiV2Url || "http://localhost:8004";
const CACHE_KEY = "openrecruiting_organizations_cache";
const CACHE_DURATION = 5 * 60 * 1000; // 5 minutes

interface Organization {
  id: string;
  name: string;
  domain: string | null;
  description: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

interface CacheData {
  organizations: Organization[];
  archivedOrganizations: Organization[];
  timestamp: number;
}

function OrganizationSkeleton() {
  return (
    <div className="bg-card rounded-xl border border-border p-6 animate-pulse">
      <div className="flex items-start justify-between mb-4">
        <div className="w-12 h-12 rounded-full bg-secondary" />
        <div className="w-16 h-3 bg-secondary rounded" />
      </div>
      <div className="h-5 bg-secondary rounded w-3/4 mb-2" />
      <div className="h-4 bg-secondary rounded w-1/2" />
      <div className="flex justify-end mt-4 pt-4 border-t border-border">
        <div className="h-8 w-20 bg-secondary rounded" />
      </div>
    </div>
  );
}

export default function CustomersPage() {
  const router = useRouter();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [archivedOrganizations, setArchivedOrganizations] = useState<Organization[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"active" | "archived">("active");
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [archiveConfirm, setArchiveConfirm] = useState<Organization | null>(null);

  const loadCachedData = useCallback(() => {
    try {
      const cached = sessionStorage.getItem(CACHE_KEY);
      if (cached) {
        const data: CacheData = JSON.parse(cached);
        const isExpired = Date.now() - data.timestamp > CACHE_DURATION;
        setOrganizations(data.organizations);
        setArchivedOrganizations(data.archivedOrganizations);
        setIsLoading(false);
        return !isExpired;
      }
    } catch {}
    return false;
  }, []);

  const saveCache = useCallback((orgs: Organization[], archived: Organization[]) => {
    try {
      const data: CacheData = {
        organizations: orgs,
        archivedOrganizations: archived,
        timestamp: Date.now(),
      };
      sessionStorage.setItem(CACHE_KEY, JSON.stringify(data));
    } catch {}
  }, []);

  const fetchOrganizations = useCallback(async (showRefreshing = false) => {
    try {
      if (showRefreshing) setIsRefreshing(true);

      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const [activeResponse, archivedResponse] = await Promise.all([
        fetch(`${API_V2_URL}/api/v2/admin/organizations`, {
          headers: { "Authorization": `Bearer ${session.access_token}` }
        }),
        fetch(`${API_V2_URL}/api/v2/admin/organizations/archived`, {
          headers: { "Authorization": `Bearer ${session.access_token}` }
        })
      ]);

      if (!activeResponse.ok) {
        throw new Error("Failed to fetch organizations");
      }

      const activeData = await activeResponse.json();
      const orgs = activeData.organizations || [];
      setOrganizations(orgs);

      let archived: Organization[] = [];
      if (archivedResponse.ok) {
        const archivedData = await archivedResponse.json();
        archived = archivedData.organizations || [];
        setArchivedOrganizations(archived);
      }

      saveCache(orgs, archived);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [router, saveCache]);

  useEffect(() => {
    const hasFreshCache = loadCachedData();
    if (hasFreshCache) {
      fetchOrganizations(true);
    } else {
      fetchOrganizations(false);
    }
  }, [loadCachedData, fetchOrganizations]);

  const handleArchiveClick = (org: Organization, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setArchiveConfirm(org);
  };

  const handleArchiveConfirm = async () => {
    if (!archiveConfirm) return;

    const orgId = archiveConfirm.id;
    setActionLoading(orgId);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      const response = await fetch(`${API_V2_URL}/api/v2/admin/organizations/${orgId}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${session?.access_token}` }
      });

      if (!response.ok) {
        throw new Error("Failed to archive organization");
      }

      const archivedOrg = organizations.find(o => o.id === orgId);
      if (archivedOrg) {
        const newOrgs = organizations.filter(o => o.id !== orgId);
        const newArchived = [...archivedOrganizations, { ...archivedOrg, deleted_at: new Date().toISOString() }];
        setOrganizations(newOrgs);
        setArchivedOrganizations(newArchived);
        saveCache(newOrgs, newArchived);
      }

      setArchiveConfirm(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to archive");
    } finally {
      setActionLoading(null);
    }
  };

  const handleRestore = async (orgId: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    setActionLoading(orgId);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      const response = await fetch(`${API_V2_URL}/api/v2/admin/organizations/${orgId}/restore`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${session?.access_token}` }
      });

      if (!response.ok) {
        throw new Error("Failed to restore organization");
      }

      const restoredOrg = archivedOrganizations.find(o => o.id === orgId);
      if (restoredOrg) {
        const newArchived = archivedOrganizations.filter(o => o.id !== orgId);
        const newOrgs = [...organizations, { ...restoredOrg, deleted_at: null }];
        setOrganizations(newOrgs);
        setArchivedOrganizations(newArchived);
        saveCache(newOrgs, newArchived);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore");
    } finally {
      setActionLoading(null);
    }
  };

  const displayedOrganizations = activeTab === "active" ? organizations : archivedOrganizations;
  const filteredOrganizations = displayedOrganizations.filter(
    org =>
      org.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (org.domain && org.domain.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <AuthGuard>
    {archiveConfirm && (
      <div id="archive-modal-overlay" className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
        <div id="archive-modal" className="bg-card rounded-xl border border-border shadow-xl max-w-md w-full p-6 animate-in zoom-in-95 duration-200">
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-full bg-orange-100 dark:bg-orange-950 flex items-center justify-center flex-shrink-0">
              <AlertTriangle className="w-5 h-5 text-orange-600" />
            </div>
            <div className="flex-1">
              <h3 id="archive-modal-title" className="text-lg font-semibold mb-2">Archive Organization</h3>
              <p id="archive-modal-description" className="text-muted-foreground text-sm mb-4">
                Are you sure you want to archive <span className="font-medium text-foreground">{archiveConfirm.name}</span>?
                All users in this organization will be disabled and unable to log in.
              </p>
              <div className="flex gap-3 justify-end">
                <button
                  id="archive-modal-cancel"
                  onClick={() => setArchiveConfirm(null)}
                  disabled={actionLoading === archiveConfirm.id}
                  className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  id="archive-modal-confirm"
                  onClick={handleArchiveConfirm}
                  disabled={actionLoading === archiveConfirm.id}
                  className="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 transition-colors disabled:opacity-50 flex items-center gap-2"
                >
                  {actionLoading === archiveConfirm.id && <Loader2 className="w-4 h-4 animate-spin" />}
                  {actionLoading === archiveConfirm.id ? "Archiving..." : "Archive"}
                </button>
              </div>
            </div>
            <button
              id="archive-modal-close"
              onClick={() => setArchiveConfirm(null)}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>
    )}
    <div id="customers-page" className="min-h-screen bg-secondary/30">
      <AdminNav />

      <main className="p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <h1 id="page-title" className="text-2xl font-bold">Organizations</h1>
            {isRefreshing && (
              <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
            )}
          </div>
          <div id="search-box" className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              id="search-input"
              type="text"
              placeholder="Search organizations..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10 pr-4 py-2 border border-border rounded-lg bg-card w-64 focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all"
            />
          </div>
        </div>

        <div id="tabs" className="flex gap-2 mb-6">
          <button
            id="tab-active"
            onClick={() => setActiveTab("active")}
            className={`px-4 py-2 rounded-lg font-medium transition-all duration-200 ${
              activeTab === "active"
                ? "bg-primary text-primary-foreground"
                : "bg-card border border-border hover:bg-secondary/50"
            }`}
          >
            Organizations ({organizations.length})
          </button>
          <button
            id="tab-archived"
            onClick={() => setActiveTab("archived")}
            className={`px-4 py-2 rounded-lg font-medium transition-all duration-200 flex items-center gap-2 ${
              activeTab === "archived"
                ? "bg-primary text-primary-foreground"
                : "bg-card border border-border hover:bg-secondary/50"
            }`}
          >
            <Archive className="w-4 h-4" />
            Archived ({archivedOrganizations.length})
          </button>
        </div>

        {isLoading ? (
          <div id="loading-state" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3, 4, 5, 6].map(i => (
              <OrganizationSkeleton key={i} />
            ))}
          </div>
        ) : error ? (
          <div id="error-state" className="bg-card rounded-xl border border-border p-12 text-center">
            <p className="text-destructive mb-4">{error}</p>
            <button
              onClick={() => { setError(""); fetchOrganizations(); }}
              className="text-primary hover:underline"
            >
              Try again
            </button>
          </div>
        ) : filteredOrganizations.length === 0 ? (
          <div id="empty-state" className="bg-card rounded-xl border border-border p-12 text-center">
            <Building2 className="w-16 h-16 mx-auto mb-4 text-muted-foreground opacity-50" />
            <h2 className="text-xl font-semibold mb-2">
              {searchQuery
                ? "No organizations found"
                : activeTab === "archived"
                  ? "No archived organizations"
                  : "No organizations yet"}
            </h2>
            <p className="text-muted-foreground mb-6">
              {searchQuery
                ? "Try adjusting your search query"
                : activeTab === "archived"
                  ? "Archived organizations will appear here"
                  : "Get started by adding your first organization"}
            </p>
            {!searchQuery && activeTab === "active" && (
              <Link
                href="/customers/new"
                className="inline-flex items-center gap-2 px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
              >
                <Plus className="w-4 h-4" />
                Add Organization
              </Link>
            )}
          </div>
        ) : (
          <div id="organizations-grid" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredOrganizations.map(org => (
              <div
                key={org.id}
                id={`organization-card-${org.id}`}
                className={`bg-card rounded-xl border border-border p-6 hover:border-primary/50 hover:shadow-md transition-all duration-200 relative group ${
                  actionLoading === org.id ? "opacity-70" : ""
                }`}
              >
                <Link href={activeTab === "active" ? `/customers/${org.id}` : "#"} className={activeTab === "archived" ? "pointer-events-none" : ""}>
                  <div className="flex items-start justify-between mb-4">
                    <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
                      <span className="text-lg font-bold text-primary">
                        {org.name.charAt(0).toUpperCase()}
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {new Date(org.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <h3 className="font-semibold text-lg mb-1">{org.name}</h3>
                  {org.domain && (
                    <p className="text-sm text-muted-foreground mb-2">{org.domain}</p>
                  )}
                </Link>

                <div className="flex justify-end mt-4 pt-4 border-t border-border">
                  {activeTab === "active" ? (
                    <button
                      id={`archive-btn-${org.id}`}
                      onClick={(e) => handleArchiveClick(org, e)}
                      disabled={actionLoading === org.id}
                      className="flex items-center gap-2 px-3 py-1.5 text-sm text-orange-600 hover:bg-orange-50 dark:hover:bg-orange-950/30 rounded-lg transition-colors disabled:opacity-50"
                    >
                      {actionLoading === org.id ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <>
                          <Trash2 className="w-4 h-4" />
                          Archive
                        </>
                      )}
                    </button>
                  ) : (
                    <button
                      id={`restore-btn-${org.id}`}
                      onClick={(e) => handleRestore(org.id, e)}
                      disabled={actionLoading === org.id}
                      className="flex items-center gap-2 px-3 py-1.5 text-sm text-green-600 hover:bg-green-50 dark:hover:bg-green-950/30 rounded-lg transition-colors disabled:opacity-50"
                    >
                      {actionLoading === org.id ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <>
                          <RotateCcw className="w-4 h-4" />
                          Restore
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
    </AuthGuard>
  );
}
