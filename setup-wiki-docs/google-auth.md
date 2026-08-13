# Google sign-in

**Optional.** Email and password sign-in works without it. Add this when you
want people to sign in with a Google account instead of managing passwords.

Fifteen minutes.

## What this gets you

A "Continue with Google" button on the sign-in page. Supabase handles the OAuth
exchange; this project only receives the resulting session.

Nothing in `.env` controls it — it is configured entirely in the Google and
Supabase dashboards. That also means the setup UI **cannot verify it**, and says
so rather than showing a tick it has not earned.

---

## 1. Create Google OAuth credentials

Go to <https://console.cloud.google.com>, create a project (or pick one).

**APIs & Services → OAuth consent screen**: choose **External**, fill in the app
name and support email, and save. You do not need to submit for verification
while testing — add your own account under **Test users**.

**APIs & Services → Credentials → Create Credentials → OAuth client ID**:

| Field | Value |
|---|---|
| Application type | Web application |
| Authorised redirect URI | `https://<your-project>.supabase.co/auth/v1/callback` |

That redirect URI is **Supabase's**, not your app's. Google sends the user back
to Supabase, which then redirects into your instance. Getting this wrong is the
single most common failure here.

Find your exact value in the Supabase dashboard under **Authentication →
Sign In / Providers → Google**; it shows the callback URL to paste.

Copy the **Client ID** and **Client secret**.

## 2. Enable the provider in Supabase

**Authentication → Sign In / Providers → Google**: toggle it on, paste the client
ID and secret, save.

## 3. Check your redirect URLs

Still in Supabase, under **Authentication → URL Configuration**, make sure your
sign-in origins are listed as redirect URLs — both the local ones and your public
hostname:

```
http://localhost:3000/**
http://localhost:3005/**
https://app.example.com/**
```

Missing entries here produce a login that appears to succeed and then bounces
back to the sign-in page. The rejection comes from Supabase, not from this app.

## Verify

Open the sign-in page, choose **Continue with Google**, and complete the flow.
You should land in the dashboard.

## Troubleshooting

**"Sign-in is temporarily unavailable" after choosing Google.** This reads like
an outage and is almost always configuration. The sign-in callback runs
*server-side inside the container* and calls the backend to complete signup; if
it cannot reach it, it fails closed and signs the user straight back out.

It uses `BACKEND_INTERNAL_URL`, which must be a container address —
`http://backend:8004` — not `localhost`. A browser-facing `NEXT_PUBLIC_` URL
here points the container at itself and produces exactly this message. Check
**Service wiring → Backend URL (server-side)** in the setup UI.

```bash
docker compose logs landing | grep -i "complete-signup"
```

**`redirect_uri_mismatch` from Google.** The authorised redirect URI does not
match Supabase's callback exactly. It must be the Supabase URL, including
`/auth/v1/callback`, with no trailing slash.

**Login loops back to the sign-in page.** Step 3 — the origin is not in
Supabase's redirect URL list.

**"Access blocked: app not verified".** Expected while the consent screen is in
testing. Add the account under **Test users**, or publish the consent screen.
