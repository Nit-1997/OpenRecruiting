# Cloudflare setup

Three things, one account, one sitting: a **domain**, a **tunnel**, and a **TURN
relay**. All three are required — see below for exactly what breaks without each.

Budget 20 minutes. The tunnel and TURN are free; a domain costs a few pounds a
year.

## What this gets you

A public address for your instance without opening a single port on your
router, plus a media relay that lets a meeting bot reach your voice agent from
Recall's cloud.

Two separate problems, which is why there are two Cloudflare products here:

- **The tunnel** carries HTTP. Recall calls your backend when a recording
  finishes; without a public address that callback never arrives, so you get no
  transcript and no feedback.
- **TURN** carries UDP media. A Recall bot's audio is UDP, which no HTTP tunnel
  can carry. Browser-to-agent voice works without it — both peers are on the
  same machine — but a bot in Recall's cloud behind your NAT has no path at all.

---

## 1. Add a domain

In the Cloudflare dashboard, either register a domain or add one you already own
and move its nameservers. You need Cloudflare to be authoritative for DNS,
because the tunnel creates DNS records for you.

Any domain works. A subdomain is fine — `recruiting.example.com`.

## 2. Create the tunnel

**Zero Trust → Networks → Tunnels → Create a tunnel**, choose **Cloudflared**,
and name it.

Cloudflare then shows an install command containing a long token. **You only need
the token**, not the command — this repo already runs `cloudflared` as a
container. Copy the token.

Then add a **public hostname** to the tunnel:

| Field | Value |
|---|---|
| Subdomain | whatever you like, e.g. `app` |
| Domain | your domain |
| Service type | **HTTP** |
| URL | `caddy:80` |

`caddy:80` is the compose service name — the tunnel container resolves it on the
internal network. It is not `localhost`.

> **One hostname, not four.** Everything is served through this single hostname
> and path-routed by Caddy: `/api/*` to the backend, `/voice-ws-v2/*` to the
> voice agent, `/mcp` to the connector, everything else to the voice frontend.
> The frontends expect the voice agent on the *same origin*, so splitting these
> across subdomains breaks voice and MCP. See `caddy/Caddyfile`.

Your public address is now `https://app.example.com`. Keep it — Recall needs it.

## 3. Create the TURN relay

**Zero Trust → Networks → TURN (Calls)** → create a TURN key.

Copy both values it gives you:

- **Turn Token ID**
- **API Token**

These are not a username and password. Cloudflare's relay does not issue
long-term credentials — the voice agent holds this key server-side and mints a
short-lived pair for each call. That is why there is no username field, and why
`voice-agent/src/ice.py` exists.

> Using a different relay? Anything with static long-term credentials — coturn,
> metered.ca — works instead. Set `TURN_SERVER_URL`, `TURN_USERNAME` and
> `TURN_CREDENTIAL` in the **Voice** group. They take priority over the
> Cloudflare pair when set.

## 4. Enter them

In the setup UI at `:3010`:

| Value | Group | Field |
|---|---|---|
| Tunnel token | Domains | Cloudflare tunnel token |
| Public address | Get started | Public address |
| Turn Token ID | Voice | Cloudflare TURN token id |
| API Token | Voice | Cloudflare TURN API token |

The public address is entered once and expands into the eight variables that
need it. Getting those out of sync used to break the MCP connector silently.

## Verify

**The tunnel is connected** — Cloudflare's Tunnels page shows it **Healthy**,
and:

```bash
docker compose logs cloudflared | grep -i "registered\|connection"
```

You want a line about a registered connection. Repeated `failed to connect`
means the token is wrong or was never applied.

**The hostname reaches your backend** — run this from anywhere, substituting your
hostname:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST https://app.example.com/api/v2/webhooks/recall/bot-status \
  -H 'Content-Type: application/json' -d '{}'
# 401
```

`401` is the healthy answer: the request reached the backend and was rejected for
having no signature. That single result proves the tunnel is up, Caddy routed
`/api/*` correctly, and the backend is running.

A `530` or `1033` is Cloudflare saying the tunnel is down. A `502` means the
tunnel is up but its service URL is wrong. A timeout means the hostname points
somewhere else entirely.

**TURN is configured** — the readiness panel on `:3010` shows **Meeting-bot
voice** as `live`.

## What breaks without it

| Missing | Consequence |
|---|---|
| Domain or tunnel | Recall records the meeting but the callback never arrives. No transcripts, no AI feedback. The MCP connector also cannot be reached. |
| TURN | The bot joins the call and stays silent — it cannot reach your voice agent. Browser voice still works, which makes this easy to misdiagnose. |

## Troubleshooting

**`cloudflared` restarts in a loop.** The token is empty or malformed. Check the
Domains group in the setup UI; a token saved but not applied leaves the container
running with the old (or no) value — press **Review & apply**.

**Tunnel is Healthy but the hostname 502s.** The public hostname's service URL is
wrong. It must be `caddy:80`, not `localhost:80` and not `backend:8004` — Caddy
is what does the path routing.

**Voice works in the browser but the bot is silent.** TURN. Check the voice agent
logs for the credential-minting line:

```bash
docker compose logs voice-agent | grep -i turn
```

A minting failure degrades to STUN-only and says so loudly, by design.

**Everything works locally but not through the hostname.** You are probably
testing `localhost` URLs. The apps' public URLs are derived from the public
address you set in **Get started**; if that still says `localhost`, the browser
gets told to talk to itself.
