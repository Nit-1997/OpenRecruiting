import { redirect } from "next/navigation";
import { Header } from "@/components/ui/header";
import { createClient } from "@/lib/supabase/server";
import { ConsentForm } from "./consent-form";

export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8000";
const LOGIN_PATH = "/login";

interface ClientMetadata {
  client_id: string;
  client_name: string | null;
  redirect_uris: string[];
  scope: string;
}

interface ConsentParams {
  response_type?: string;
  client_id?: string;
  redirect_uri?: string;
  code_challenge?: string;
  code_challenge_method?: string;
  scope?: string;
  state?: string;
  audience?: string;
}

async function fetchClientMetadata(clientId: string): Promise<ClientMetadata | null> {
  try {
    const resp = await fetch(`${API_URL}/api/v2/mcp/oauth/clients/${encodeURIComponent(clientId)}`, {
      cache: "no-store",
    });
    if (!resp.ok) return null;
    return (await resp.json()) as ClientMetadata;
  } catch {
    return null;
  }
}

function describeScope(scope: string): string {
  const map: Record<string, string> = {
    "cortex:read":
      "Read your organization's recruitment-intelligence graph (candidates, requisitions, feedback, traits)",
  };
  return map[scope] ?? scope;
}

function buildLoginRedirectUrl(params: ConsentParams): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const here = `/oauth/consent?${qs.toString()}`;
  return `${LOGIN_PATH}?redirect=${encodeURIComponent(here)}`;
}

export default async function ConsentPage({
  searchParams,
}: {
  searchParams: Promise<ConsentParams>;
}) {
  const params = await searchParams;

  // --- Validate required params ---
  const required: (keyof ConsentParams)[] = [
    "response_type",
    "client_id",
    "redirect_uri",
    "code_challenge",
    "audience",
  ];
  const missing = required.filter((k) => !params[k]);
  if (missing.length > 0) {
    return (
      <main className="mx-auto max-w-md px-6 py-24">
        <Header variant="light" />
        <div className="mt-16 rounded-2xl border border-red-200 bg-red-50 p-6">
          <h1 className="text-lg font-semibold text-red-900">Invalid authorization request</h1>
          <p className="mt-2 text-sm text-red-800">
            Missing required parameter(s): {missing.join(", ")}. Return to the MCP client that
            initiated this request and try again.
          </p>
        </div>
      </main>
    );
  }

  // --- Require OpenRecruiting session ---
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect(buildLoginRedirectUrl(params));
  }

  // --- Fetch client metadata for display ---
  const client = await fetchClientMetadata(params.client_id!);
  if (!client) {
    return (
      <main className="mx-auto max-w-md px-6 py-24">
        <Header variant="light" />
        <div className="mt-16 rounded-2xl border border-red-200 bg-red-50 p-6">
          <h1 className="text-lg font-semibold text-red-900">Unknown application</h1>
          <p className="mt-2 text-sm text-red-800">
            We couldn&apos;t find the application that requested access. The link may be
            expired or the MCP client misconfigured.
          </p>
        </div>
      </main>
    );
  }

  // --- Render consent ---
  const scopeItems = (params.scope || "cortex:read").split(/\s+/).filter(Boolean);
  const clientName = client.client_name || "An MCP application";

  return (
    <>
      <Header variant="light" />
      <main className="mx-auto max-w-md px-6 py-16">
        <div className="rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
          <h1 id="consent-title" className="text-xl font-semibold text-gray-900">
            {clientName} wants to access OpenRecruiting Cortex
          </h1>
          <p id="consent-signed-in" className="mt-3 rounded-lg bg-gray-50 px-4 py-3 text-sm text-gray-700">
            Signed in as <strong>{user!.email}</strong>
          </p>
          <p id="consent-grant-intro" className="mt-6 text-sm text-gray-600">
            This will allow {clientName} to:
          </p>
          <ul id="consent-scope-list" className="mt-3 space-y-2">
            {scopeItems.map((s) => (
              <li
                id={`consent-scope-${s.replace(/:/g, "-")}`}
                key={s}
                className="flex items-start gap-2 text-sm text-gray-800"
              >
                <span className="mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600" />
                <span>{describeScope(s)}</span>
              </li>
            ))}
          </ul>
          <ConsentForm
            params={{
              client_id: params.client_id!,
              redirect_uri: params.redirect_uri!,
              code_challenge: params.code_challenge!,
              code_challenge_method: params.code_challenge_method || "S256",
              scope: params.scope || "cortex:read",
              state: params.state || "",
              audience: params.audience!,
            }}
          />
          <p id="consent-revoke-hint" className="mt-6 text-xs text-gray-500">
            You can revoke this access at any time from your OpenRecruiting account settings.
          </p>
        </div>
      </main>
    </>
  );
}
