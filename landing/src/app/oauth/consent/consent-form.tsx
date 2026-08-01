"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

interface ConsentFormProps {
  params: {
    client_id: string;
    redirect_uri: string;
    code_challenge: string;
    code_challenge_method: string;
    scope: string;
    state: string;
    audience: string;
  };
}

export function ConsentForm({ params }: ConsentFormProps) {
  const [submitting, setSubmitting] = useState<"allow" | "deny" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(decision: "allow" | "deny") {
    if (submitting) return;
    setError(null);
    setSubmitting(decision);
    try {
      const form = new URLSearchParams({ ...params, decision });
      const resp = await fetch("/oauth/consent/submit", {
        method: "POST",
        body: form,
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      });
      const body = (await resp.json()) as { redirect_url?: string; error?: string };
      if (!resp.ok || !body.redirect_url) {
        setError(body.error || `Authorization failed (HTTP ${resp.status})`);
        setSubmitting(null);
        return;
      }
      window.location.href = body.redirect_url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
      setSubmitting(null);
    }
  }

  return (
    <div id="consent-actions" className="mt-8">
      {error && (
        <p id="consent-error" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </p>
      )}
      <div className="flex gap-3">
        <Button
          id="consent-deny-btn"
          type="button"
          variant="outline"
          className="flex-1"
          disabled={submitting !== null}
          onClick={() => submit("deny")}
        >
          {submitting === "deny" ? "Denying…" : "Deny"}
        </Button>
        <Button
          id="consent-allow-btn"
          type="button"
          className="flex-1"
          disabled={submitting !== null}
          onClick={() => submit("allow")}
        >
          {submitting === "allow" ? "Authorizing…" : "Allow"}
        </Button>
      </div>
    </div>
  );
}
