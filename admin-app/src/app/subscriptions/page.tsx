"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { CreditCard, Plus, Pencil, Loader2, X, AlertTriangle } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { createClient } from "@/lib/supabase/client";
import { getRuntimeConfig } from "@/lib/runtime-config";


// V2 backend base — admin endpoints ported to /api/v2/admin.

const API_V2_URL = getRuntimeConfig().apiV2Url || "http://localhost:8004";
const CACHE_KEY = "openrecruiting_subscriptions_cache";
const CACHE_DURATION = 5 * 60 * 1000;

const PLAN_OPTIONS = ["individual", "enterprise"] as const;
type PlanName = (typeof PLAN_OPTIONS)[number];

interface Subscription {
  id: string;
  organization_id: string;
  org_name: string;
  plan_name: string;
  status: string;
  is_manual: boolean;
  custom_price_cents: number | null;
  custom_intake_credits: number | null;
  custom_interview_credits: number | null;
  custom_max_users: number | null;
  current_period_start: string | null;
  current_period_end: string | null;
  created_at: string;
}

interface Organization {
  id: string;
  name: string;
}

interface CacheData {
  subscriptions: Subscription[];
  timestamp: number;
}

interface SubscriptionForm {
  organization_id: string;
  plan_name: PlanName;
  custom_price_dollars: string;
  custom_intake_credits: string;
  custom_interview_credits: string;
  custom_max_users: string;
  current_period_end: string;
}

const emptyForm: SubscriptionForm = {
  organization_id: "",
  plan_name: "enterprise",
  custom_price_dollars: "",
  custom_intake_credits: "",
  custom_interview_credits: "",
  custom_max_users: "",
  current_period_end: "",
};

function TableSkeleton() {
  return (
    <div id="subscriptions-skeleton" className="bg-card rounded-xl border border-border animate-pulse">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="flex items-center gap-4 px-6 py-4 border-b border-border last:border-b-0">
          <div className="h-4 bg-secondary rounded w-32" />
          <div className="h-4 bg-secondary rounded w-16" />
          <div className="h-6 bg-secondary rounded-full w-16" />
          <div className="h-4 bg-secondary rounded w-20 ml-auto" />
        </div>
      ))}
    </div>
  );
}

export default function SubscriptionsPage() {
  const router = useRouter();
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"all" | "active" | "manual">("all");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingSubscription, setEditingSubscription] = useState<Subscription | null>(null);
  const [form, setForm] = useState<SubscriptionForm>(emptyForm);
  const [formError, setFormError] = useState("");
  const [formLoading, setFormLoading] = useState(false);
  const [cancelConfirm, setCancelConfirm] = useState<Subscription | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [creditsMap, setCreditsMap] = useState<Record<string, { intake: { used: number; total: number }; interview: { used: number; total: number } }>>({});

  const loadCachedData = useCallback(() => {
    try {
      const cached = sessionStorage.getItem(CACHE_KEY);
      if (cached) {
        const data: CacheData = JSON.parse(cached);
        const isExpired = Date.now() - data.timestamp > CACHE_DURATION;
        setSubscriptions(data.subscriptions);
        setIsLoading(false);
        return !isExpired;
      }
    } catch {}
    return false;
  }, []);

  const saveCache = useCallback((subs: Subscription[]) => {
    try {
      const data: CacheData = { subscriptions: subs, timestamp: Date.now() };
      sessionStorage.setItem(CACHE_KEY, JSON.stringify(data));
    } catch {}
  }, []);

  const getToken = useCallback(async () => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) {
      router.push("/login");
      return null;
    }
    return session.access_token;
  }, [router]);

  const fetchCreditsForOrgs = useCallback(async (subs: Subscription[]) => {
    const token = await getToken();
    if (!token) return;
    const orgIds = [...new Set(subs.filter(s => s.status === "active").map(s => s.organization_id))];
    const map: typeof creditsMap = {};
    await Promise.all(orgIds.map(async (orgId) => {
      try {
        const resp = await fetch(`${API_V2_URL}/api/v2/admin/billing/organizations/${orgId}/credits`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) return;
        const data = await resp.json();
        const entry = { intake: { used: 0, total: 0 }, interview: { used: 0, total: 0 } };
        for (const c of data.credits || []) {
          const ct = c.credit_type as "intake" | "interview";
          if (ct === "intake" || ct === "interview") {
            entry[ct] = { used: c.used, total: c.total };
          }
        }
        map[orgId] = entry;
      } catch {}
    }));
    setCreditsMap(map);
  }, [getToken]);

  const fetchSubscriptions = useCallback(async (showRefreshing = false) => {
    try {
      if (showRefreshing) setIsRefreshing(true);
      const token = await getToken();
      if (!token) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/billing/subscriptions`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!response.ok) throw new Error("Failed to fetch subscriptions");

      const data = await response.json();
      const subs = data.subscriptions || data || [];
      setSubscriptions(subs);
      saveCache(subs);
      fetchCreditsForOrgs(subs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [getToken, saveCache, fetchCreditsForOrgs]);

  const fetchOrganizations = useCallback(async () => {
    try {
      const token = await getToken();
      if (!token) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/organizations`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!response.ok) return;

      const data = await response.json();
      setOrganizations(data.organizations || data || []);
    } catch {}
  }, [getToken]);

  useEffect(() => {
    const hasFreshCache = loadCachedData();
    if (hasFreshCache) {
      fetchSubscriptions(true);
    } else {
      fetchSubscriptions(false);
    }
    fetchOrganizations();
  }, [loadCachedData, fetchSubscriptions, fetchOrganizations]);

  const openCreateModal = () => {
    setEditingSubscription(null);
    setForm(emptyForm);
    setFormError("");
    setModalOpen(true);
  };

  const openEditModal = (sub: Subscription) => {
    setEditingSubscription(sub);
    setForm({
      organization_id: sub.organization_id,
      plan_name: sub.plan_name as PlanName,
      custom_price_dollars: sub.custom_price_cents != null ? String(sub.custom_price_cents / 100) : "",
      custom_intake_credits: sub.custom_intake_credits != null ? String(sub.custom_intake_credits) : "",
      custom_interview_credits: sub.custom_interview_credits != null ? String(sub.custom_interview_credits) : "",
      custom_max_users: sub.custom_max_users != null ? String(sub.custom_max_users) : "",
      current_period_end: sub.current_period_end ? sub.current_period_end.split("T")[0] : "",
    });
    setFormError("");
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    if (!editingSubscription && !form.organization_id) {
      setFormError("Organization is required");
      return;
    }

    setFormLoading(true);
    setFormError("");

    try {
      const token = await getToken();
      if (!token) return;

      const body: Record<string, unknown> = {
        plan_name: form.plan_name,
      };

      if (!editingSubscription) {
        body.organization_id = form.organization_id;
      }

      if (form.custom_price_dollars !== "") body.custom_price_dollars = parseFloat(form.custom_price_dollars);
      if (form.custom_intake_credits !== "") body.custom_intake_credits = parseInt(form.custom_intake_credits);
      if (form.custom_interview_credits !== "") body.custom_interview_credits = parseInt(form.custom_interview_credits);
      if (form.custom_max_users !== "") body.custom_max_users = parseInt(form.custom_max_users);
      if (form.current_period_end !== "") body.current_period_end = new Date(form.current_period_end).toISOString();

      const isEdit = !!editingSubscription;
      const url = isEdit
        ? `${API_V2_URL}/api/v2/admin/billing/subscriptions/${editingSubscription.id}`
        : `${API_V2_URL}/api/v2/admin/billing/subscriptions`;

      const response = await fetch(url, {
        method: isEdit ? "PUT" : "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => null);
        throw new Error(errData?.detail || `Failed to ${isEdit ? "update" : "create"} subscription`);
      }

      setModalOpen(false);
      fetchSubscriptions(true);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setFormLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!cancelConfirm) return;
    setActionLoading(cancelConfirm.id);

    try {
      const token = await getToken();
      if (!token) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/billing/subscriptions/${cancelConfirm.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!response.ok) throw new Error("Failed to cancel subscription");

      setCancelConfirm(null);
      fetchSubscriptions(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel");
    } finally {
      setActionLoading(null);
    }
  };

  const formatPrice = (cents: number | null) => {
    if (cents == null) return "\u2014";
    return `$${(cents / 100).toFixed(2)}`;
  };

  const formatCredits = (credits: number | null) => {
    if (credits == null) return "\u2014";
    if (credits === -1) return "Unlimited";
    return String(credits);
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "\u2014";
    return new Date(dateStr).toLocaleDateString();
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "active":
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400">
            Active
          </span>
        );
      case "canceled":
      case "cancelled":
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400">
            Canceled
          </span>
        );
      case "past_due":
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400">
            Past Due
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
            {status}
          </span>
        );
    }
  };

  const filteredSubscriptions = subscriptions.filter((sub) => {
    if (activeTab === "active") return sub.status === "active";
    if (activeTab === "manual") return sub.is_manual;
    return true;
  });

  return (
    <AuthGuard>
      {modalOpen && (
        <div id="subscription-modal-overlay" className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div id="subscription-modal" className="bg-card rounded-xl border border-border shadow-xl max-w-lg w-full p-6 animate-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between mb-6">
              <h3 id="subscription-modal-title" className="text-lg font-semibold">
                {editingSubscription ? "Edit Subscription" : "Create Manual Subscription"}
              </h3>
              <button
                id="subscription-modal-close"
                onClick={() => setModalOpen(false)}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {formError && (
              <div id="subscription-form-error" className="bg-destructive/10 text-destructive border border-destructive/20 rounded-lg p-3 mb-4 text-sm">
                {formError}
              </div>
            )}

            <div className="space-y-4">
              {!editingSubscription && (
                <div>
                  <label id="subscription-org-label" htmlFor="subscription-org-select" className="block text-sm font-medium mb-1">
                    Organization
                  </label>
                  <select
                    id="subscription-org-select"
                    value={form.organization_id}
                    onChange={(e) => setForm({ ...form, organization_id: e.target.value })}
                    className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
                  >
                    <option value="">Select an organization</option>
                    {organizations.map((org) => (
                      <option key={org.id} value={org.id}>
                        {org.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div>
                <label id="subscription-plan-label" htmlFor="subscription-plan-select" className="block text-sm font-medium mb-1">
                  Plan
                </label>
                <select
                  id="subscription-plan-select"
                  value={form.plan_name}
                  onChange={(e) => setForm({ ...form, plan_name: e.target.value as PlanName })}
                  className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
                >
                  {PLAN_OPTIONS.map((plan) => (
                    <option key={plan} value={plan}>
                      {plan.charAt(0).toUpperCase() + plan.slice(1)}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label id="subscription-price-label" htmlFor="subscription-price-input" className="block text-sm font-medium mb-1">
                    Price ($)
                  </label>
                  <input
                    id="subscription-price-input"
                    type="number"
                    min={0}
                    step="0.01"
                    value={form.custom_price_dollars}
                    onChange={(e) => setForm({ ...form, custom_price_dollars: e.target.value })}
                    placeholder="e.g. 499"
                    className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
                <div>
                  <label id="subscription-period-end-label" htmlFor="subscription-period-end-input" className="block text-sm font-medium mb-1">
                    Billing Period End
                  </label>
                  <input
                    id="subscription-period-end-input"
                    type="date"
                    value={form.current_period_end}
                    onChange={(e) => setForm({ ...form, current_period_end: e.target.value })}
                    className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label id="subscription-intake-label" htmlFor="subscription-intake-input" className="block text-sm font-medium mb-1">
                    Intake Credits (optional)
                  </label>
                  <input
                    id="subscription-intake-input"
                    type="number"
                    min={-1}
                    value={form.custom_intake_credits}
                    onChange={(e) => setForm({ ...form, custom_intake_credits: e.target.value })}
                    placeholder="-1 = unlimited"
                    className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
                <div>
                  <label id="subscription-interview-label" htmlFor="subscription-interview-input" className="block text-sm font-medium mb-1">
                    Interview Credits (optional)
                  </label>
                  <input
                    id="subscription-interview-input"
                    type="number"
                    min={-1}
                    value={form.custom_interview_credits}
                    onChange={(e) => setForm({ ...form, custom_interview_credits: e.target.value })}
                    placeholder="-1 = unlimited"
                    className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
              </div>

              <div>
                <label id="subscription-maxusers-label" htmlFor="subscription-maxusers-input" className="block text-sm font-medium mb-1">
                  Custom Max Users (optional)
                </label>
                <input
                  id="subscription-maxusers-input"
                  type="number"
                  min={1}
                  value={form.custom_max_users}
                  onChange={(e) => setForm({ ...form, custom_max_users: e.target.value })}
                  placeholder="Leave empty for plan default"
                  className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 mt-6 pt-4 border-t border-border">
              <button
                id="subscription-modal-cancel"
                onClick={() => setModalOpen(false)}
                disabled={formLoading}
                className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                id="subscription-modal-submit"
                onClick={handleSubmit}
                disabled={formLoading}
                className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {formLoading && <Loader2 className="w-4 h-4 animate-spin" />}
                {formLoading ? "Saving..." : editingSubscription ? "Update" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {cancelConfirm && (
        <div id="subscription-cancel-overlay" className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div id="subscription-cancel-modal" className="bg-card rounded-xl border border-border shadow-xl max-w-md w-full p-6 animate-in zoom-in-95 duration-200">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-destructive/10 flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="w-5 h-5 text-destructive" />
              </div>
              <div className="flex-1">
                <h3 id="subscription-cancel-title" className="text-lg font-semibold mb-2">Cancel Subscription</h3>
                <p id="subscription-cancel-description" className="text-muted-foreground text-sm mb-4">
                  Are you sure you want to cancel the subscription for <span className="font-medium text-foreground">{cancelConfirm.org_name}</span> ({cancelConfirm.plan_name} plan)?
                </p>
                <div className="flex gap-3 justify-end">
                  <button
                    id="subscription-cancel-dismiss"
                    onClick={() => setCancelConfirm(null)}
                    disabled={actionLoading === cancelConfirm.id}
                    className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
                  >
                    Keep
                  </button>
                  <button
                    id="subscription-cancel-confirm"
                    onClick={handleCancel}
                    disabled={actionLoading === cancelConfirm.id}
                    className="px-4 py-2 bg-destructive text-destructive-foreground rounded-lg hover:bg-destructive/90 transition-colors disabled:opacity-50 flex items-center gap-2"
                  >
                    {actionLoading === cancelConfirm.id && <Loader2 className="w-4 h-4 animate-spin" />}
                    {actionLoading === cancelConfirm.id ? "Canceling..." : "Cancel Subscription"}
                  </button>
                </div>
              </div>
              <button
                id="subscription-cancel-close"
                onClick={() => setCancelConfirm(null)}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      )}

      <div id="subscriptions-page" className="min-h-screen bg-secondary/30">
        <AdminNav />

        <main id="subscriptions-main" className="p-6">
          <div id="subscriptions-header" className="flex items-center justify-between mb-8">
            <div>
              <h1 id="subscriptions-title" className="text-3xl font-bold flex items-center gap-3">
                <CreditCard className="w-8 h-8 text-primary" />
                Subscriptions
              </h1>
              <p id="subscriptions-subtitle" className="text-muted-foreground mt-1">
                Manage organization billing and subscription plans
              </p>
            </div>
            <div className="flex items-center gap-3">
              {isRefreshing && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}
              <button
                id="subscriptions-create-btn"
                onClick={openCreateModal}
                className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
              >
                <Plus className="w-4 h-4" />
                Create Manual Subscription
              </button>
            </div>
          </div>

          <div id="subscriptions-tabs" className="flex gap-2 mb-6">
            {(["all", "active", "manual"] as const).map((tab) => (
              <button
                key={tab}
                id={`subscriptions-tab-${tab}`}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 rounded-lg font-medium transition-all duration-200 ${
                  activeTab === tab
                    ? "bg-primary text-primary-foreground"
                    : "bg-card border border-border hover:bg-secondary/50"
                }`}
              >
                {tab === "all" && `All (${subscriptions.length})`}
                {tab === "active" && `Active (${subscriptions.filter((s) => s.status === "active").length})`}
                {tab === "manual" && `Manual Only (${subscriptions.filter((s) => s.is_manual).length})`}
              </button>
            ))}
          </div>

          {error && (
            <div id="subscriptions-error" className="bg-destructive/10 text-destructive border border-destructive/20 rounded-lg p-4 mb-6">
              {error}
              <button
                id="subscriptions-error-dismiss"
                onClick={() => setError("")}
                className="ml-4 underline text-sm"
              >
                Dismiss
              </button>
            </div>
          )}

          {isLoading ? (
            <TableSkeleton />
          ) : filteredSubscriptions.length === 0 ? (
            <div id="subscriptions-empty" className="bg-card rounded-xl border border-border p-12 text-center">
              <CreditCard className="w-16 h-16 mx-auto mb-4 text-muted-foreground opacity-50" />
              <h2 id="subscriptions-empty-title" className="text-xl font-semibold mb-2">
                {activeTab === "all" ? "No subscriptions yet" : `No ${activeTab} subscriptions`}
              </h2>
              <p id="subscriptions-empty-description" className="text-muted-foreground mb-6">
                {activeTab === "all"
                  ? "Create a manual subscription to get started"
                  : "Try a different filter"}
              </p>
              {activeTab === "all" && (
                <button
                  id="subscriptions-empty-create"
                  onClick={openCreateModal}
                  className="inline-flex items-center gap-2 px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  Create Manual Subscription
                </button>
              )}
            </div>
          ) : (
            <div id="subscriptions-table-wrapper" className="bg-card rounded-xl border border-border overflow-hidden">
              <div className="overflow-x-auto">
                <table id="subscriptions-table" className="w-full">
                  <thead id="subscriptions-table-head">
                    <tr className="border-b border-border bg-secondary/30">
                      <th id="subscriptions-th-org" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Organization</th>
                      <th id="subscriptions-th-plan" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Plan</th>
                      <th id="subscriptions-th-status" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Status</th>
                      <th id="subscriptions-th-manual" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Manual</th>
                      <th id="subscriptions-th-price" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Price</th>
                      <th id="subscriptions-th-intake" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Intake (left/total)</th>
                      <th id="subscriptions-th-interview" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Interview (left/total)</th>
                      <th id="subscriptions-th-period" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Period</th>
                      <th id="subscriptions-th-actions" className="text-right px-6 py-3 text-sm font-medium text-muted-foreground">Actions</th>
                    </tr>
                  </thead>
                  <tbody id="subscriptions-table-body">
                    {filteredSubscriptions.map((sub) => (
                      <tr
                        key={sub.id}
                        id={`subscription-row-${sub.id}`}
                        className="border-b border-border last:border-b-0 hover:bg-secondary/20 transition-colors"
                      >
                        <td id={`subscription-org-${sub.id}`} className="px-6 py-4 text-sm font-medium">
                          {sub.org_name}
                        </td>
                        <td id={`subscription-plan-${sub.id}`} className="px-6 py-4 text-sm capitalize">
                          {sub.plan_name}
                        </td>
                        <td id={`subscription-status-${sub.id}`} className="px-6 py-4">
                          {getStatusBadge(sub.status)}
                        </td>
                        <td id={`subscription-manual-${sub.id}`} className="px-6 py-4">
                          <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${
                            sub.is_manual
                              ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"
                              : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                          }`}>
                            {sub.is_manual ? "Manual" : "Stripe"}
                          </span>
                        </td>
                        <td id={`subscription-price-${sub.id}`} className="px-6 py-4 text-sm text-muted-foreground">
                          {formatPrice(sub.custom_price_cents)}
                        </td>
                        <td id={`subscription-intake-${sub.id}`} className="px-6 py-4 text-sm text-muted-foreground">
                          {creditsMap[sub.organization_id] ? (
                            <span title={`Used: ${creditsMap[sub.organization_id].intake.used}, Total: ${creditsMap[sub.organization_id].intake.total === -1 ? "∞" : creditsMap[sub.organization_id].intake.total}`}>
                              {creditsMap[sub.organization_id].intake.total === -1
                                ? `${creditsMap[sub.organization_id].intake.used} / ∞`
                                : `${creditsMap[sub.organization_id].intake.total - creditsMap[sub.organization_id].intake.used} / ${creditsMap[sub.organization_id].intake.total}`
                              }
                            </span>
                          ) : formatCredits(sub.custom_intake_credits)}
                        </td>
                        <td id={`subscription-interview-${sub.id}`} className="px-6 py-4 text-sm text-muted-foreground">
                          {creditsMap[sub.organization_id] ? (
                            <span title={`Used: ${creditsMap[sub.organization_id].interview.used}, Total: ${creditsMap[sub.organization_id].interview.total === -1 ? "∞" : creditsMap[sub.organization_id].interview.total}`}>
                              {creditsMap[sub.organization_id].interview.total === -1
                                ? `${creditsMap[sub.organization_id].interview.used} / ∞`
                                : `${creditsMap[sub.organization_id].interview.total - creditsMap[sub.organization_id].interview.used} / ${creditsMap[sub.organization_id].interview.total}`
                              }
                            </span>
                          ) : formatCredits(sub.custom_interview_credits)}
                        </td>
                        <td id={`subscription-period-${sub.id}`} className="px-6 py-4 text-sm text-muted-foreground whitespace-nowrap">
                          {formatDate(sub.current_period_start)} - {formatDate(sub.current_period_end)}
                        </td>
                        <td id={`subscription-actions-${sub.id}`} className="px-6 py-4">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              id={`subscription-edit-${sub.id}`}
                              onClick={() => openEditModal(sub)}
                              className="p-2 hover:bg-secondary rounded-lg transition-colors"
                              title="Edit"
                            >
                              <Pencil className="w-4 h-4" />
                            </button>
                            {sub.status === "active" && (
                              <button
                                id={`subscription-cancel-${sub.id}`}
                                onClick={() => setCancelConfirm(sub)}
                                className="p-2 hover:bg-destructive/10 text-destructive rounded-lg transition-colors"
                                title="Cancel"
                              >
                                <X className="w-4 h-4" />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </main>
      </div>
    </AuthGuard>
  );
}
