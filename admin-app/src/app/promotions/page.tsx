"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Tag, Plus, Pencil, Trash2, Loader2, X, AlertTriangle, Power } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { createClient } from "@/lib/supabase/client";
import { getRuntimeConfig } from "@/lib/runtime-config";

// V2 backend base — these admin endpoints are ported to /api/v2/admin.
const API_V2_URL = getRuntimeConfig().apiV2Url || "http://localhost:8004";
const CACHE_KEY = "openrecruiting_promotions_cache";
const CACHE_DURATION = 5 * 60 * 1000;

interface Promotion {
  id: string;
  code: string;
  percent_off: number;
  is_active: boolean;
  start_date: string | null;
  end_date: string | null;
  created_at: string;
}

interface CacheData {
  promotions: Promotion[];
  timestamp: number;
}

interface PromotionForm {
  code: string;
  percent_off: number;
  start_date: string;
  end_date: string;
}

const emptyForm: PromotionForm = {
  code: "",
  percent_off: 0,
  start_date: "",
  end_date: "",
};

function TableSkeleton() {
  return (
    <div id="promotions-skeleton" className="bg-card rounded-xl border border-border animate-pulse">
      {[1, 2, 3].map((i) => (
        <div key={i} className="flex items-center gap-4 px-6 py-4 border-b border-border last:border-b-0">
          <div className="h-4 bg-secondary rounded w-24" />
          <div className="h-4 bg-secondary rounded w-12" />
          <div className="h-6 bg-secondary rounded-full w-16" />
          <div className="h-4 bg-secondary rounded w-20 ml-auto" />
        </div>
      ))}
    </div>
  );
}

export default function PromotionsPage() {
  const router = useRouter();
  const [promotions, setPromotions] = useState<Promotion[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingPromotion, setEditingPromotion] = useState<Promotion | null>(null);
  const [form, setForm] = useState<PromotionForm>(emptyForm);
  const [formError, setFormError] = useState("");
  const [formLoading, setFormLoading] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<Promotion | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const loadCachedData = useCallback(() => {
    try {
      const cached = sessionStorage.getItem(CACHE_KEY);
      if (cached) {
        const data: CacheData = JSON.parse(cached);
        const isExpired = Date.now() - data.timestamp > CACHE_DURATION;
        setPromotions(data.promotions);
        setIsLoading(false);
        return !isExpired;
      }
    } catch {}
    return false;
  }, []);

  const saveCache = useCallback((promos: Promotion[]) => {
    try {
      const data: CacheData = { promotions: promos, timestamp: Date.now() };
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

  const fetchPromotions = useCallback(async (showRefreshing = false) => {
    try {
      if (showRefreshing) setIsRefreshing(true);
      const token = await getToken();
      if (!token) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/promotions`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!response.ok) throw new Error("Failed to fetch promotions");

      const data = await response.json();
      const promos = data.items || data.promotions || (Array.isArray(data) ? data : []);
      setPromotions(promos);
      saveCache(promos);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [getToken, saveCache]);

  useEffect(() => {
    const hasFreshCache = loadCachedData();
    if (hasFreshCache) {
      fetchPromotions(true);
    } else {
      fetchPromotions(false);
    }
  }, [loadCachedData, fetchPromotions]);

  const openCreateModal = () => {
    setEditingPromotion(null);
    setForm(emptyForm);
    setFormError("");
    setModalOpen(true);
  };

  const openEditModal = (promo: Promotion) => {
    setEditingPromotion(promo);
    setForm({
      code: promo.code,
      percent_off: promo.percent_off,
      start_date: promo.start_date ? promo.start_date.split("T")[0] : "",
      end_date: promo.end_date ? promo.end_date.split("T")[0] : "",
    });
    setFormError("");
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    if (!form.code.trim()) {
      setFormError("Code is required");
      return;
    }
    if (form.percent_off < 1 || form.percent_off > 100) {
      setFormError("Percent off must be between 1 and 100");
      return;
    }

    setFormLoading(true);
    setFormError("");

    try {
      const token = await getToken();
      if (!token) return;

      const body: Record<string, unknown> = {
        code: form.code.trim().toUpperCase(),
        percent_off: form.percent_off,
        is_active: true,
      };
      if (form.start_date) body.start_date = form.start_date;
      if (form.end_date) body.end_date = form.end_date;

      const isEdit = !!editingPromotion;
      const url = isEdit
        ? `${API_V2_URL}/api/v2/admin/promotions/${editingPromotion.id}`
        : `${API_V2_URL}/api/v2/admin/promotions`;

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
        throw new Error(errData?.detail || `Failed to ${isEdit ? "update" : "create"} promotion`);
      }

      setModalOpen(false);
      fetchPromotions(true);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setFormLoading(false);
    }
  };

  const handleToggleActive = async (promo: Promotion) => {
    setActionLoading(promo.id);
    setError("");

    try {
      const token = await getToken();
      if (!token) return;

      const newActive = !promo.is_active;
      const response = await fetch(`${API_V2_URL}/api/v2/admin/promotions/${promo.id}`, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ is_active: newActive }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => null);
        throw new Error(errData?.detail || "Failed to update promotion");
      }

      await fetchPromotions(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to toggle promotion");
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async () => {
    if (!deleteConfirm) return;
    setActionLoading(deleteConfirm.id);

    try {
      const token = await getToken();
      if (!token) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/promotions/${deleteConfirm.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!response.ok) throw new Error("Failed to delete promotion");

      const updated = promotions.filter((p) => p.id !== deleteConfirm.id);
      setPromotions(updated);
      saveCache(updated);
      setDeleteConfirm(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setActionLoading(null);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "\u2014";
    return new Date(dateStr).toLocaleDateString();
  };

  const activePromo = promotions.find((p) => p.is_active);

  return (
    <AuthGuard>
      {modalOpen && (
        <div id="promotion-modal-overlay" className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div id="promotion-modal" className="bg-card rounded-xl border border-border shadow-xl max-w-lg w-full p-6 animate-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between mb-6">
              <h3 id="promotion-modal-title" className="text-lg font-semibold">
                {editingPromotion ? "Edit Promotion" : "Create Promotion"}
              </h3>
              <button
                id="promotion-modal-close"
                onClick={() => setModalOpen(false)}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {formError && (
              <div id="promotion-form-error" className="bg-destructive/10 text-destructive border border-destructive/20 rounded-lg p-3 mb-4 text-sm">
                {formError}
              </div>
            )}

            <div className="space-y-4">
              <div>
                <label id="promotion-code-label" htmlFor="promotion-code-input" className="block text-sm font-medium mb-1">
                  Code
                </label>
                <input
                  id="promotion-code-input"
                  type="text"
                  value={form.code}
                  onChange={(e) => setForm({ ...form, code: e.target.value })}
                  placeholder="e.g. SUMMER25"
                  className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50 uppercase"
                />
              </div>

              <div>
                <label id="promotion-percent-label" htmlFor="promotion-percent-input" className="block text-sm font-medium mb-1">
                  Percent Off
                </label>
                <input
                  id="promotion-percent-input"
                  type="number"
                  min={1}
                  max={100}
                  value={form.percent_off}
                  onChange={(e) => setForm({ ...form, percent_off: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label id="promotion-start-label" htmlFor="promotion-start-input" className="block text-sm font-medium mb-1">
                    Start Date (optional)
                  </label>
                  <input
                    id="promotion-start-input"
                    type="date"
                    value={form.start_date}
                    onChange={(e) => setForm({ ...form, start_date: e.target.value })}
                    className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
                <div>
                  <label id="promotion-end-label" htmlFor="promotion-end-input" className="block text-sm font-medium mb-1">
                    End Date (optional)
                  </label>
                  <input
                    id="promotion-end-input"
                    type="date"
                    value={form.end_date}
                    onChange={(e) => setForm({ ...form, end_date: e.target.value })}
                    className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
              </div>
            </div>

            <p id="promotion-active-note" className="text-xs text-muted-foreground mt-4">
              Creating or saving will automatically activate this promotion and deactivate any other active one.
            </p>

            <div className="flex justify-end gap-3 mt-4 pt-4 border-t border-border">
              <button
                id="promotion-modal-cancel"
                onClick={() => setModalOpen(false)}
                disabled={formLoading}
                className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                id="promotion-modal-submit"
                onClick={handleSubmit}
                disabled={formLoading}
                className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {formLoading && <Loader2 className="w-4 h-4 animate-spin" />}
                {formLoading ? "Saving..." : editingPromotion ? "Save & Activate" : "Create & Activate"}
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteConfirm && (
        <div id="promotion-delete-overlay" className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div id="promotion-delete-modal" className="bg-card rounded-xl border border-border shadow-xl max-w-md w-full p-6 animate-in zoom-in-95 duration-200">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-destructive/10 flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="w-5 h-5 text-destructive" />
              </div>
              <div className="flex-1">
                <h3 id="promotion-delete-title" className="text-lg font-semibold mb-2">Delete Promotion</h3>
                <p id="promotion-delete-description" className="text-muted-foreground text-sm mb-4">
                  Are you sure you want to delete <span className="font-medium text-foreground">{deleteConfirm.code}</span>?
                  {deleteConfirm.is_active && " This is the currently active promotion — deleting it will remove the discount from the website."}
                </p>
                <div className="flex gap-3 justify-end">
                  <button
                    id="promotion-delete-cancel"
                    onClick={() => setDeleteConfirm(null)}
                    disabled={actionLoading === deleteConfirm.id}
                    className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    id="promotion-delete-confirm"
                    onClick={handleDelete}
                    disabled={actionLoading === deleteConfirm.id}
                    className="px-4 py-2 bg-destructive text-destructive-foreground rounded-lg hover:bg-destructive/90 transition-colors disabled:opacity-50 flex items-center gap-2"
                  >
                    {actionLoading === deleteConfirm.id && <Loader2 className="w-4 h-4 animate-spin" />}
                    {actionLoading === deleteConfirm.id ? "Deleting..." : "Delete"}
                  </button>
                </div>
              </div>
              <button
                id="promotion-delete-close"
                onClick={() => setDeleteConfirm(null)}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      )}

      <div id="promotions-page" className="min-h-screen bg-secondary/30">
        <AdminNav />

        <main id="promotions-main" className="p-6">
          <div id="promotions-header" className="flex items-center justify-between mb-8">
            <div>
              <h1 id="promotions-title" className="text-3xl font-bold flex items-center gap-3">
                <Tag className="w-8 h-8 text-primary" />
                Promotions
              </h1>
              <p id="promotions-subtitle" className="text-muted-foreground mt-1">
                Manage discount codes. Only one promotion can be active on the website at a time.
              </p>
            </div>
            <div className="flex items-center gap-3">
              {isRefreshing && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}
              <button
                id="promotions-create-btn"
                onClick={openCreateModal}
                className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
              >
                <Plus className="w-4 h-4" />
                Create Promotion
              </button>
            </div>
          </div>

          {activePromo && (
            <div id="promotions-active-banner" className="bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 rounded-xl px-5 py-4 mb-6 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span id="promotions-active-badge" className="text-xs font-semibold px-2.5 py-1 rounded bg-green-600 text-white">LIVE</span>
                <span id="promotions-active-code" className="font-mono font-semibold">{activePromo.code}</span>
                <span className="text-green-800 dark:text-green-300">&mdash; {activePromo.percent_off}% off all paid plans</span>
              </div>
              <button
                id="promotions-active-disable-btn"
                onClick={() => handleToggleActive(activePromo)}
                disabled={actionLoading === activePromo.id}
                className="flex items-center gap-2 px-3 py-1.5 text-sm bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 rounded-lg hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors disabled:opacity-50"
              >
                {actionLoading === activePromo.id ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Power className="w-3.5 h-3.5" />
                )}
                Disable
              </button>
            </div>
          )}

          {!activePromo && !isLoading && promotions.length > 0 && (
            <div id="promotions-none-active" className="bg-zinc-50 dark:bg-zinc-900/20 border border-zinc-200 dark:border-zinc-800 rounded-xl px-5 py-4 mb-6">
              <span className="text-sm text-muted-foreground">No promotion is currently active. The website shows regular pricing.</span>
            </div>
          )}

          {error && (
            <div id="promotions-error" className="bg-destructive/10 text-destructive border border-destructive/20 rounded-lg p-4 mb-6">
              {error}
              <button
                id="promotions-error-dismiss"
                onClick={() => setError("")}
                className="ml-4 underline text-sm"
              >
                Dismiss
              </button>
            </div>
          )}

          {isLoading ? (
            <TableSkeleton />
          ) : promotions.length === 0 ? (
            <div id="promotions-empty" className="bg-card rounded-xl border border-border p-12 text-center">
              <Tag className="w-16 h-16 mx-auto mb-4 text-muted-foreground opacity-50" />
              <h2 id="promotions-empty-title" className="text-xl font-semibold mb-2">No promotions yet</h2>
              <p id="promotions-empty-description" className="text-muted-foreground mb-6">
                Create a promotion to show discounted pricing on the website.
              </p>
              <button
                id="promotions-empty-create"
                onClick={openCreateModal}
                className="inline-flex items-center gap-2 px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
              >
                <Plus className="w-4 h-4" />
                Create Promotion
              </button>
            </div>
          ) : (
            <div id="promotions-table-wrapper" className="bg-card rounded-xl border border-border overflow-hidden">
              <table id="promotions-table" className="w-full">
                <thead id="promotions-table-head">
                  <tr className="border-b border-border bg-secondary/30">
                    <th id="promotions-th-code" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Code</th>
                    <th id="promotions-th-percent" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Discount</th>
                    <th id="promotions-th-status" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Status</th>
                    <th id="promotions-th-dates" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Dates</th>
                    <th id="promotions-th-actions" className="text-right px-6 py-3 text-sm font-medium text-muted-foreground">Actions</th>
                  </tr>
                </thead>
                <tbody id="promotions-table-body">
                  {promotions.map((promo) => (
                    <tr
                      key={promo.id}
                      id={`promotion-row-${promo.id}`}
                      className={`border-b border-border last:border-b-0 hover:bg-secondary/20 transition-colors ${
                        promo.is_active ? "bg-green-50/30 dark:bg-green-950/10" : ""
                      }`}
                    >
                      <td id={`promotion-code-${promo.id}`} className="px-6 py-4 font-mono font-semibold text-sm">
                        {promo.code}
                      </td>
                      <td id={`promotion-percent-${promo.id}`} className="px-6 py-4 text-sm">
                        {promo.percent_off}% off
                      </td>
                      <td id={`promotion-status-${promo.id}`} className="px-6 py-4">
                        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${
                          promo.is_active
                            ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                            : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                        }`}>
                          {promo.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td id={`promotion-dates-${promo.id}`} className="px-6 py-4 text-sm text-muted-foreground">
                        {formatDate(promo.start_date)} &mdash; {formatDate(promo.end_date)}
                      </td>
                      <td id={`promotion-actions-${promo.id}`} className="px-6 py-4">
                        <div className="flex items-center justify-end gap-1">
                          {promo.is_active ? (
                            <button
                              id={`promotion-disable-${promo.id}`}
                              onClick={() => handleToggleActive(promo)}
                              disabled={actionLoading === promo.id}
                              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 rounded-lg hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors disabled:opacity-50"
                            >
                              {actionLoading === promo.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Power className="w-3.5 h-3.5" />}
                              Disable
                            </button>
                          ) : (
                            <button
                              id={`promotion-enable-${promo.id}`}
                              onClick={() => handleToggleActive(promo)}
                              disabled={actionLoading === promo.id}
                              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 rounded-lg hover:bg-green-200 dark:hover:bg-green-900/50 transition-colors disabled:opacity-50"
                            >
                              {actionLoading === promo.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Power className="w-3.5 h-3.5" />}
                              Activate
                            </button>
                          )}
                          <button
                            id={`promotion-edit-${promo.id}`}
                            onClick={() => openEditModal(promo)}
                            className="p-2 hover:bg-secondary rounded-lg transition-colors"
                            title="Edit"
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button
                            id={`promotion-delete-${promo.id}`}
                            onClick={() => setDeleteConfirm(promo)}
                            className="p-2 hover:bg-destructive/10 text-destructive rounded-lg transition-colors"
                            title="Delete"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </main>
      </div>
    </AuthGuard>
  );
}
