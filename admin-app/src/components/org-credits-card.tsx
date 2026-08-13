"use client";

import { useState, useEffect, useCallback } from "react";
import { Coins, Loader2, Pencil, Check, X, Infinity as InfinityIcon } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { getRuntimeConfig } from "@/lib/runtime-config";

const API_V2_URL = getRuntimeConfig().apiV2Url || "http://localhost:8004";

// -1 is the unlimited sentinel stored in usage_credits.total.
const UNLIMITED = -1;

interface CreditRow {
  credit_type: string;
  total: number;
  used: number;
  remaining: number | "unlimited";
}

export function OrgCreditsCard({ orgId }: { orgId: string }) {
  const [credits, setCredits] = useState<CreditRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  const [isEditing, setIsEditing] = useState(false);
  const [intakeDraft, setIntakeDraft] = useState("");
  const [interviewDraft, setInterviewDraft] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const rowFor = useCallback(
    (type: string) => credits.find((c) => c.credit_type === type),
    [credits],
  );

  const fetchCredits = useCallback(async () => {
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) return;

      const response = await fetch(
        `${API_V2_URL}/api/v2/admin/organizations/${orgId}/credits`,
        { headers: { Authorization: `Bearer ${session.access_token}` } },
      );
      if (!response.ok) throw new Error("Failed to load credits");

      const data = await response.json();
      setCredits(data.credits || []);
      setError("");
    } catch {
      setError("Could not load credits");
    } finally {
      setIsLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    fetchCredits();
  }, [fetchCredits]);

  const startEditing = () => {
    setIntakeDraft(String(rowFor("intake")?.total ?? 0));
    setInterviewDraft(String(rowFor("interview")?.total ?? 0));
    setError("");
    setIsEditing(true);
  };

  const save = async () => {
    const intake = Number(intakeDraft);
    const interview = Number(interviewDraft);

    if (!Number.isInteger(intake) || !Number.isInteger(interview)) {
      setError("Credits must be whole numbers");
      return;
    }
    if (intake < UNLIMITED || interview < UNLIMITED) {
      setError("Use -1 for unlimited, or 0 and above");
      return;
    }

    setIsSaving(true);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) return;

      const response = await fetch(
        `${API_V2_URL}/api/v2/admin/organizations/${orgId}/credits`,
        {
          method: "PUT",
          headers: {
            Authorization: `Bearer ${session.access_token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ intake_total: intake, interview_total: interview }),
        },
      );
      if (!response.ok) throw new Error("Failed to save");

      const data = await response.json();
      setCredits(data.credits || []);
      setIsEditing(false);
      setError("");
    } catch {
      setError("Could not save credits");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div id="org-credits-card" className="bg-card rounded-xl border border-border p-6">
      <div id="org-credits-header" className="flex items-center justify-between mb-4">
        <h2 id="org-credits-heading" className="font-semibold flex items-center gap-2">
          <Coins className="w-4 h-4" />
          Credit Budget
        </h2>
        {!isLoading && !isEditing && (
          <button
            id="org-credits-edit-btn"
            onClick={startEditing}
            className="p-1.5 rounded-lg hover:bg-secondary transition-colors"
            aria-label="Edit credit budget"
          >
            <Pencil className="w-3.5 h-3.5 text-muted-foreground" />
          </button>
        )}
        {isEditing && (
          <div id="org-credits-edit-actions" className="flex items-center gap-1">
            <button
              id="org-credits-save-btn"
              onClick={save}
              disabled={isSaving}
              className="p-1.5 rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
              aria-label="Save credit budget"
            >
              {isSaving ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Check className="w-3.5 h-3.5 text-primary" />
              )}
            </button>
            <button
              id="org-credits-cancel-btn"
              onClick={() => { setIsEditing(false); setError(""); }}
              disabled={isSaving}
              className="p-1.5 rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
              aria-label="Cancel"
            >
              <X className="w-3.5 h-3.5 text-muted-foreground" />
            </button>
          </div>
        )}
      </div>

      {isLoading ? (
        <div id="org-credits-loading" className="space-y-3">
          <div className="h-12 bg-secondary rounded-lg animate-pulse" />
          <div className="h-12 bg-secondary rounded-lg animate-pulse" />
        </div>
      ) : isEditing ? (
        <div id="org-credits-editor" className="space-y-3">
          <CreditInput
            id="org-credits-input-interview"
            label="Interviews"
            value={interviewDraft}
            onChange={setInterviewDraft}
          />
          <CreditInput
            id="org-credits-input-intake"
            label="Intakes"
            value={intakeDraft}
            onChange={setIntakeDraft}
          />
          <p id="org-credits-hint" className="text-xs text-muted-foreground">
            Shared across everyone in this organization. Use -1 for unlimited.
          </p>
        </div>
      ) : (
        <div id="org-credits-meters" className="space-y-3">
          <CreditMeter id="org-credits-interview" label="Interviews" row={rowFor("interview")} />
          <CreditMeter id="org-credits-intake" label="Intakes" row={rowFor("intake")} />
        </div>
      )}

      {error && (
        <p id="org-credits-error" className="mt-3 text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

function CreditInput({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div id={`${id}-wrap`}>
      <label id={`${id}-label`} htmlFor={id} className="text-sm text-muted-foreground">
        {label}
      </label>
      <input
        id={id}
        type="number"
        value={value}
        min={UNLIMITED}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full px-3 py-2 rounded-lg border border-border bg-background text-sm"
      />
    </div>
  );
}

function CreditMeter({
  id,
  label,
  row,
}: {
  id: string;
  label: string;
  row?: CreditRow;
}) {
  // No row means the org predates provisioning — it has no budget rather than
  // a zeroed one, and the first charge will lazily grant it one credit.
  if (!row) {
    return (
      <div id={id} className="rounded-lg border border-border px-3 py-2.5">
        <p id={`${id}-label`} className="text-sm text-muted-foreground">{label}</p>
        <p id={`${id}-value`} className="text-sm text-muted-foreground italic">Not provisioned</p>
      </div>
    );
  }

  const unlimited = row.total === UNLIMITED;
  const remaining = unlimited ? 0 : Math.max(0, row.total - row.used);
  const pct = unlimited || row.total === 0 ? 0 : (row.used / row.total) * 100;
  const depleted = !unlimited && remaining === 0;

  return (
    <div id={id} className="rounded-lg border border-border px-3 py-2.5">
      <div id={`${id}-row`} className="flex items-baseline justify-between">
        <p id={`${id}-label`} className="text-sm text-muted-foreground">{label}</p>
        <p id={`${id}-value`} className="text-sm font-medium tabular-nums">
          {unlimited ? (
            <span id={`${id}-unlimited`} className="flex items-center gap-1">
              <InfinityIcon className="w-3.5 h-3.5" />
              unlimited
            </span>
          ) : (
            <>
              <span className={depleted ? "text-destructive" : ""}>{remaining}</span>
              <span className="text-muted-foreground"> / {row.total}</span>
            </>
          )}
        </p>
      </div>
      {!unlimited && (
        <div id={`${id}-bar`} className="mt-2 h-1.5 rounded-full bg-secondary overflow-hidden">
          <div
            id={`${id}-bar-fill`}
            className={`h-full transition-all ${depleted ? "bg-destructive" : "bg-primary"}`}
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
      )}
      <p id={`${id}-used`} className="mt-1.5 text-xs text-muted-foreground">
        {row.used} used
      </p>
    </div>
  );
}
