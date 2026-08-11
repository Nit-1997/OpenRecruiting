"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { createClient } from "@/lib/supabase/client";
import { getRuntimeConfig } from "@/lib/runtime-config";


// V2 backend base — admin endpoints ported to /api/v2/admin.

const API_V2_URL = getRuntimeConfig().apiV2Url || "http://localhost:8004";

export default function NewOrganizationPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !email.trim() || !company.trim()) return;

    setIsSubmitting(true);
    setError("");

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        setError("Not authenticated");
        setIsSubmitting(false);
        return;
      }

      const orgResponse = await fetch(`${API_V2_URL}/api/v2/admin/organizations`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${session.access_token}`
        },
        body: JSON.stringify({
          name: company.trim(),
          domain: email.split("@")[1]
        })
      });

      if (!orgResponse.ok) {
        const errData = await orgResponse.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to create organization");
      }

      const org = await orgResponse.json();

      const userResponse = await fetch(
        `${API_V2_URL}/api/v2/admin/organizations/${org.id}/users`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${session.access_token}`
          },
          body: JSON.stringify({
            email: email.trim().toLowerCase(),
            full_name: name.trim(),
            role: "owner"
          })
        }
      );

      if (!userResponse.ok) {
        const errData = await userResponse.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to create user");
      }

      router.push(`/customers/${org.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
      setIsSubmitting(false);
    }
  };

  const isValid = name.trim() && email.trim() && company.trim();

  return (
    <AuthGuard>
    <div id="new-organization-page" className="min-h-screen bg-secondary/30">
      <AdminNav />

      <main className="p-6">
        <div className="max-w-2xl mx-auto">
          <div className="flex items-center gap-4 mb-6">
            <Link id="back-link" href="/customers" className="p-2 hover:bg-secondary rounded-lg transition-colors">
              <ArrowLeft className="w-5 h-5" />
            </Link>
            <h1 id="page-title" className="text-2xl font-bold">Add New Organization</h1>
          </div>

          <form id="new-organization-form" onSubmit={handleSubmit} className="bg-card rounded-xl border border-border p-8">
            <div className="space-y-6">
              <div id="company-field">
                <label htmlFor="organization-name" className="block text-sm font-medium mb-2">
                  Organization Name <span className="text-destructive">*</span>
                </label>
                <input
                  id="organization-name"
                  type="text"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  placeholder="Acme Inc."
                  className="w-full px-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                  required
                />
              </div>

              <div id="name-field">
                <label htmlFor="contact-name" className="block text-sm font-medium mb-2">
                  Contact Name <span className="text-destructive">*</span>
                </label>
                <input
                  id="contact-name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="John Doe"
                  className="w-full px-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                  required
                />
              </div>

              <div id="email-field">
                <label htmlFor="contact-email" className="block text-sm font-medium mb-2">
                  Contact Email <span className="text-destructive">*</span>
                </label>
                <input
                  id="contact-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="john@company.com"
                  className="w-full px-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                  required
                />
                <p id="email-hint" className="text-sm text-muted-foreground mt-1">A magic link invitation will be sent to this email</p>
              </div>

              {error && (
                <div id="error-message" className="p-3 bg-destructive/10 text-destructive text-sm rounded-lg">
                  {error}
                </div>
              )}

              <div id="form-actions" className="flex items-center justify-end gap-4 pt-4">
                <Link
                  id="cancel-btn"
                  href="/customers"
                  className="px-6 py-3 border border-border rounded-lg hover:bg-secondary transition-colors"
                >
                  Cancel
                </Link>
                <button
                  id="submit-btn"
                  type="submit"
                  disabled={!isValid || isSubmitting}
                  className="px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isSubmitting ? "Creating..." : "Create Organization"}
                </button>
              </div>
            </div>
          </form>
        </div>
      </main>
    </div>
    </AuthGuard>
  );
}
