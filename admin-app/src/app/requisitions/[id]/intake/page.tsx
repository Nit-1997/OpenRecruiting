"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Building2,
  ArrowLeft,
  X,
  Plus,
  ChevronRight,
  MapPin,
  Briefcase,
  LogOut,
  Loader2,
  Save,
  Check,
  AlertCircle,
} from "lucide-react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { AuthGuard } from "@/components/auth-guard";
import { createClient } from "@/lib/supabase/client";
import { getRuntimeConfig } from "@/lib/runtime-config";

interface Requisition {
  id: string;
  organization_id: string;
  role_title: string;
  role_location: string | null;
  experience_min_years: number;
  experience_max_years: number | null;
  experience_display: string;
  job_description: string | null;
  must_have_skills: string[];
  good_to_have_skills: string[];
  additional_notes: string | null;
  status: string;
  created_at: string;
}

interface Organization {
  id: string;
  name: string;
}

export default function IntakePage() {
  const params = useParams();
  const router = useRouter();
  const reqId = params.id as string;

  const [requisition, setRequisition] = useState<Requisition | null>(null);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const [jobDescription, setJobDescription] = useState("");
  const [mustHaveSkills, setMustHaveSkills] = useState<string[]>([]);
  const [goodToHaveSkills, setGoodToHaveSkills] = useState<string[]>([]);
  const [additionalNotes, setAdditionalNotes] = useState("");
  const [newMustHave, setNewMustHave] = useState("");
  const [newGoodToHave, setNewGoodToHave] = useState("");

  
  // V2 backend base — admin endpoints ported to /api/v2/admin.

  const API_V2_URL = getRuntimeConfig().apiV2Url || "http://localhost:8004";

  useEffect(() => {
    fetchRequisition();
  }, [reqId]);

  const fetchRequisition = async () => {
    try {
      setLoading(true);
      setError(null);

      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const headers = {
        "Authorization": `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
      };

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}`, { headers });
      if (!response.ok) {
        throw new Error("Failed to fetch requisition");
      }
      const data = await response.json();
      setRequisition(data);
      setJobDescription(data.job_description || "");
      setMustHaveSkills(data.must_have_skills || []);
      setGoodToHaveSkills(data.good_to_have_skills || []);
      setAdditionalNotes(data.intake_notes || "");

      const orgResponse = await fetch(`${API_V2_URL}/api/v2/admin/organizations/${data.organization_id}`, { headers });
      if (orgResponse.ok) {
        const orgData = await orgResponse.json();
        setOrganization(orgData);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch requisition");
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("admin_auth");
    router.push("/login");
  };

  const handleAddMustHave = () => {
    if (newMustHave.trim() && !mustHaveSkills.includes(newMustHave.trim())) {
      setMustHaveSkills([...mustHaveSkills, newMustHave.trim()]);
      setNewMustHave("");
    }
  };

  const handleAddGoodToHave = () => {
    if (newGoodToHave.trim() && !goodToHaveSkills.includes(newGoodToHave.trim())) {
      setGoodToHaveSkills([...goodToHaveSkills, newGoodToHave.trim()]);
      setNewGoodToHave("");
    }
  };

  const handleRemoveMustHave = (index: number) => {
    setMustHaveSkills(mustHaveSkills.filter((_, i) => i !== index));
  };

  const handleRemoveGoodToHave = (index: number) => {
    setGoodToHaveSkills(goodToHaveSkills.filter((_, i) => i !== index));
  };

  const handleSave = async (): Promise<boolean> => {
    if (!requisition) return false;

    try {
      setSaving(true);
      setError(null);
      setSaveSuccess(false);

      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return false;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}/intake`, {
        method: "PUT",
        headers: {
          "Authorization": `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          job_description: jobDescription || null,
          must_have_skills: mustHaveSkills,
          good_to_have_skills: goodToHaveSkills,
          intake_notes: additionalNotes || null,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to save intake notes");
      }

      const updated = await response.json();
      setRequisition(updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
      return false;
    } finally {
      setSaving(false);
    }
  };

  const validateIntake = (): boolean => {
    setValidationError(null);
    return true;
  };

  const handleProceedToPlan = async () => {
    if (!validateIntake()) {
      return;
    }
    const saved = await handleSave();
    if (saved) {
      router.push(`/requisitions/${reqId}/plan`);
    }
  };

  if (loading) {
    return (
      <div id="intake-loading" className="min-h-screen bg-secondary/30 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error || !requisition) {
    return (
      <div id="intake-error" className="min-h-screen bg-secondary/30 flex items-center justify-center">
        <div className="text-center">
          <p className="text-destructive mb-4">{error || "Requisition not found"}</p>
          <Link href="/customers" className="text-primary hover:underline">
            Back to customers
          </Link>
        </div>
      </div>
    );
  }

  return (
    <AuthGuard>
      <div id="intake-page" className="min-h-screen bg-secondary/30">
        <nav id="intake-nav" className="bg-card border-b border-border">
          <div className="px-6 py-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Link href="/" className="flex items-center gap-3">
                <Building2 className="w-8 h-8 text-primary" />
                <span className="text-xl font-bold">OpenRecruiting Admin</span>
              </Link>
            </div>
            <div className="flex items-center gap-4">
              {organization && (
                <Link
                  href={`/customers/${requisition.organization_id}`}
                  id="back-to-org-link"
                  className="flex items-center gap-2 px-4 py-2 rounded-lg hover:bg-secondary transition-colors text-sm"
                >
                  <ArrowLeft className="w-4 h-4" />
                  Back to {organization.name}
                </Link>
              )}
              <ThemeToggle />
              <button
                id="intake-logout-btn"
                onClick={handleLogout}
                className="flex items-center gap-2 px-4 py-2 text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
              >
                <LogOut className="w-4 h-4" />
                Logout
              </button>
            </div>
          </div>
        </nav>

        <div id="intake-progress" className="w-full bg-card border-b border-border px-6 py-4">
          <div className="max-w-4xl mx-auto">
            <div id="intake-progress-bar" className="relative flex justify-between items-start">
              <div id="intake-progress-line-bg" className="absolute top-4 left-8 right-8 h-0.5 bg-border" />
              <div
                id="intake-progress-line-active"
                className="absolute top-4 left-8 h-0.5 bg-primary transition-all duration-500"
                style={{ width: "16%" }}
              />
              {[
                { id: "basic", label: "Basic Info", complete: true },
                { id: "intake", label: "Intake Notes", active: true },
                { id: "plan", label: "Interview Plan", complete: false },
              ].map((step, index) => (
                <div key={step.id} id={`intake-step-${step.id}`} className="flex flex-col items-center relative z-10 w-28">
                  <div
                    id={`intake-dot-${step.id}`}
                    className={`w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all duration-300 ${
                      step.complete
                        ? "bg-primary border-primary"
                        : step.active
                        ? "border-primary bg-card"
                        : "border-border bg-card"
                    }`}
                  >
                    {step.complete && (
                      <svg className="w-4 h-4 text-primary-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                    {step.active && <div className="w-2 h-2 rounded-full bg-primary" />}
                  </div>
                  <p
                    id={`intake-label-${step.id}`}
                    className={`text-xs mt-2 text-center ${
                      step.complete || step.active ? "text-foreground font-medium" : "text-muted-foreground"
                    }`}
                  >
                    {step.label}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <main id="intake-main" className="max-w-3xl mx-auto p-6">
          <div id="intake-header" className="mb-6">
            <h1 id="intake-title" className="text-2xl font-bold mb-2">
              Intake Notes: {requisition.role_title}
            </h1>
            <div className="flex items-center gap-4 text-muted-foreground">
              {requisition.role_location && (
                <span id="intake-location" className="flex items-center gap-1">
                  <MapPin className="w-4 h-4" />
                  {requisition.role_location}
                </span>
              )}
              <span id="intake-experience" className="flex items-center gap-1">
                <Briefcase className="w-4 h-4" />
                {requisition.experience_display}
              </span>
            </div>
          </div>

          <div id="intake-form-card" className="bg-card rounded-2xl border border-border p-8">
            <div className="space-y-6">
              <div id="job-description-field">
                <label htmlFor="job-description-input" className="block text-sm font-medium mb-2">
                  Job Description
                </label>
                <textarea
                  id="job-description-input"
                  value={jobDescription}
                  onChange={(e) => setJobDescription(e.target.value)}
                  placeholder="Paste or type the full job description..."
                  rows={8}
                  className="w-full px-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none font-mono text-sm"
                />
              </div>

              <div id="must-have-skills-field">
                <label className="block text-sm font-medium mb-2">Must Have Skills</label>
                <div className="flex gap-2 mb-2">
                  <input
                    id="must-have-skill-input"
                    type="text"
                    value={newMustHave}
                    onChange={(e) => setNewMustHave(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddMustHave();
                      }
                    }}
                    placeholder="Add a must-have skill..."
                    className="flex-1 px-4 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                  <button
                    id="add-must-have-btn"
                    type="button"
                    onClick={handleAddMustHave}
                    className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
                  >
                    Add
                  </button>
                </div>
                <div id="must-have-tags" className="flex flex-wrap gap-2">
                  {mustHaveSkills.map((skill, i) => (
                    <span
                      key={i}
                      id={`must-have-tag-${i}`}
                      className="flex items-center gap-1 px-3 py-1 bg-primary/10 text-primary rounded-full text-sm"
                    >
                      {skill}
                      <button
                        onClick={() => handleRemoveMustHave(i)}
                        className="hover:text-destructive"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              </div>

              <div id="good-to-have-skills-field">
                <label className="block text-sm font-medium mb-2">Good to Have Skills</label>
                <div className="flex gap-2 mb-2">
                  <input
                    id="good-to-have-skill-input"
                    type="text"
                    value={newGoodToHave}
                    onChange={(e) => setNewGoodToHave(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddGoodToHave();
                      }
                    }}
                    placeholder="Add a good-to-have skill..."
                    className="flex-1 px-4 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                  <button
                    id="add-good-to-have-btn"
                    type="button"
                    onClick={handleAddGoodToHave}
                    className="px-4 py-2 bg-secondary text-secondary-foreground rounded-lg hover:bg-secondary/80"
                  >
                    Add
                  </button>
                </div>
                <div id="good-to-have-tags" className="flex flex-wrap gap-2">
                  {goodToHaveSkills.map((skill, i) => (
                    <span
                      key={i}
                      id={`good-to-have-tag-${i}`}
                      className="flex items-center gap-1 px-3 py-1 bg-secondary text-secondary-foreground rounded-full text-sm"
                    >
                      {skill}
                      <button
                        onClick={() => handleRemoveGoodToHave(i)}
                        className="hover:text-destructive"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              </div>

              <div id="additional-notes-field">
                <label htmlFor="additional-notes-input" className="block text-sm font-medium mb-2">
                  Additional Notes
                </label>
                <textarea
                  id="additional-notes-input"
                  value={additionalNotes}
                  onChange={(e) => setAdditionalNotes(e.target.value)}
                  placeholder="Notes from the intake call with the hiring manager..."
                  rows={4}
                  className="w-full px-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
                />
              </div>

              {(saveSuccess || validationError || error) && (
                <div id="intake-messages" className="pt-4">
                  {saveSuccess && (
                    <div id="save-success-message" className="flex items-center gap-2 text-green-600 dark:text-green-400 text-sm">
                      <Check className="w-4 h-4" />
                      Progress saved successfully!
                    </div>
                  )}
                  {validationError && (
                    <div id="validation-error-message" className="flex items-center gap-2 text-destructive text-sm">
                      <AlertCircle className="w-4 h-4" />
                      {validationError}
                    </div>
                  )}
                  {error && (
                    <div id="save-error-message" className="flex items-center gap-2 text-destructive text-sm">
                      <AlertCircle className="w-4 h-4" />
                      {error}
                    </div>
                  )}
                </div>
              )}

              <div id="intake-actions" className="flex justify-between pt-4">
                <button
                  id="save-intake-btn"
                  onClick={() => handleSave()}
                  disabled={saving}
                  className="flex items-center gap-2 px-6 py-3 border border-border rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
                >
                  {saving ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : saveSuccess ? (
                    <Check className="w-4 h-4 text-green-600" />
                  ) : (
                    <Save className="w-4 h-4" />
                  )}
                  {saveSuccess ? "Saved!" : "Save Progress"}
                </button>
                <button
                  id="proceed-to-plan-btn"
                  onClick={handleProceedToPlan}
                  disabled={saving}
                  className="flex items-center gap-2 px-8 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {saving && <Loader2 className="w-4 h-4 animate-spin" />}
                  Proceed to Interview Plan
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        </main>
      </div>
    </AuthGuard>
  );
}
