# Email setup

Required. Ten minutes, most of it waiting for a DNS record.

## What this gets you

Every message the platform sends to someone who is not logged in:

- interview invitations to candidates,
- feedback links to interviewers,
- password resets and magic-link sign-ins.

Without it none of those are sent, and **nothing reports an error** — the send is
simply never attempted. That makes it one of the easier things to leave broken
without noticing.

Two providers are implemented: **Resend** (simplest) and **Zoho ZeptoMail**.
SendGrid and Postmark appear in the code's provider list but raise at send time,
so do not choose them.

---

## Resend

### 1. Create an account and verify a domain

Sign up at <https://resend.com>. **Domains → Add Domain**, enter a domain you
control, and add the DNS records it shows you.

If your domain is on Cloudflare — likely, since you set up a tunnel there — add
these in the Cloudflare DNS tab. **Turn the proxy off** (grey cloud, not orange)
for the mail records; proxying breaks them.

Verification usually takes a few minutes.

> You can send without a verified domain using Resend's sandbox address, but
> only to your own email. That is fine for testing step 8 of the setup and
> useless for real candidates.

### 2. Create an API key

**API Keys → Create API Key**, with sending permission. Copy it — it is shown
once.

### 3. Enter it

In the setup UI at `:3010`, **Email** group:

| Field | Value |
|---|---|
| Provider | `resend` |
| From address | e.g. `hiring@yourdomain.com` — must be on the verified domain |
| From name | e.g. `Acme Talent` |
| Resend API key | the key from step 2 |

The provider field decides which key is read. Setting a Resend key while the
provider still says `zoho` sends nothing.

---

## Zoho ZeptoMail — alternative

If you already use Zoho, set **Provider** to `zoho`, paste your **ZeptoMail API
token**, and leave the base URL at its default unless your account is in a
different region.

Everything else is identical.

---

## Verify

The readiness panel on `:3010` shows **Email** as `live`. If it says
`incomplete`, it names exactly which field is missing.

The real test is end to end: invite a user to an organization from the admin
portal at `:3001` and confirm the magic link arrives. That exercises the same
path a candidate invitation takes.

If it does not arrive, check the backend rather than guessing:

```bash
docker compose logs backend | grep -i "email\|resend\|zepto"
```

## What breaks without it

| | |
|---|---|
| Candidate invitations | never sent — the candidate is never told about the interview |
| Interviewer feedback links | never sent — no feedback is ever collected |
| Password resets and magic links | never sent — invited users cannot get in |

Note the last one. If you invite a teammate before configuring email, they
receive nothing and have no way to sign in.

## Troubleshooting

**Nothing sends and there is no error.** The provider is unset or does not match
the key you filled in. `EMAIL_PROVIDER` must be exactly `resend` or `zoho`.

**`403` or "domain not verified".** DNS has not propagated, or the records are
proxied. On Cloudflare the mail records must be grey-cloud, not orange.

**Mail sends but lands in spam.** Your domain is new and has no sending
reputation. Add DMARC alongside the SPF and DKIM records Resend gave you.

**"From address" rejected.** It must be on the domain you verified. A Gmail
address will not work.
