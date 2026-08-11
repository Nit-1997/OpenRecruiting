# Public endpoints and the WebRTC media path — design

**Status:** approved design, not yet planned
**Date:** 2026-08-11
**Sub-projects 2 and 3 of 4** in the "easy self-hosted setup" effort. Sub-project 1
(the settings UI) is COMPLETE.

## Goal

A self-hoster on a laptop can (a) receive Recall webhooks, (b) connect Claude to
the MCP server, and (c) have a Recall meeting bot actually speak in a Google Meet
— without a cloud VM and without editing `.env` by hand.

## The shape of the problem

Not "add ngrok". Established by reading the code on 2026-08-11:

| # | endpoint | who reaches it | protocol |
|---|---|---|---|
| 1 | `backend:8004` | Recall posts webhooks (`WEBHOOK_BASE_URL`) | HTTP |
| 2 | `voice-frontend:3003` | Recall's **cloud browser loads this page** as the bot's camera (`VOICE_AGENT_URL`) | HTTP |
| 3 | `voice-agent:8011` | that page's WebRTC signalling | HTTP |
| 4 | `cortex-mcp:8020` | Claude's connector | HTTP |
| 5 | media | Recall's browser ↔ `voice-agent` | **UDP** |

### Two constraints that rule out the naive approach

1. **#2 and #3 must share an origin.** `recruiter-app/src/components/sub-agents/
   intake/IntakeCallProvider.tsx:57` builds the offer URL as
   `${protocol}//${host}/voice-ws-v2/v2/intake/offer` — voice-agent is expected at
   a PATH on the same host. Four independent tunnels give four hostnames and
   break this.
2. **The reverse proxy that provided `/voice-ws-v2` is not in this repo.** It
   lived in `deploy-config/`, which is absent from the checkout. Self-hosters have
   never had it.

### Why it worked on AWS and cannot work through a tunnel

`recall_service.py:210-215` creates the bot with
`output_media.camera = {kind: "webpage", config: {url: VOICE_AGENT_URL/<token>}}`.
Recall runs a **cloud browser**, loads that page, and streams its output into the
meeting. The page then does WebRTC to `voice-agent`.

On AWS the agent had a public IP with UDP 40000-40010 open, so the browser
reached it directly via host/srflx ICE candidates. Behind NAT there is no such
path — and **no HTTP tunnel fixes it**: ngrok and Cloudflare Tunnel carry TCP,
while WebRTC media is UDP.

## Decisions

| # | decision | rejected alternative, and why |
|---|---|---|
| D1 | **A Caddy reverse proxy in compose**, path-routing one hostname to all four services. | Tunnelling each service separately gives four hostnames and breaks the `/voice-ws-v2` same-origin assumption, forcing frontend changes in three call sites. One compose service is cheaper than scattered edits. |
| D2 | **Cloudflare Tunnel** in front of Caddy. | ngrok free churns its hostname on every restart, which the project's own notes already record as a recurring "webhooks went quiet" failure. A stable hostname ends that; a reserved ngrok domain costs money to achieve the same thing. |
| D3 | **Cloudflare TURN** for the media path. | Self-hosted coturn means operating a relay; Twilio bills per GB and voice relays continuously. Cloudflare's free tier pairs with D2 — one vendor. |
| D4 | **TURN, not a wider tunnel**, is the answer to #5. | There is no HTTP tunnel that carries WebRTC media. TURN relays it outbound from BOTH peers, so NAT stops mattering. |

## What already exists

- `voice-agent/src/main.py:79-88` `_build_ice_servers()` already appends a TURN
  server when `turn_server_url` is set and passes it to
  `SmallWebRTCRequestHandler`.

### ⚠️ CORRECTION — Cloudflare TURN needs code, not just config

An earlier revision of this spec said "the media fix is configuration, not
code." That is TRUE for a provider with long-term static credentials
(self-hosted coturn, metered.ca) and FALSE for the provider chosen in D3.

Cloudflare TURN issues **ephemeral** credentials: you hold a TURN key
(`TURN_KEY_ID` + API token) server-side and mint short-lived username/password
pairs from
`https://rtc.live.cloudflare.com/v1/turn/keys/$TURN_KEY_ID/credentials/generate-ice-servers`.
`_build_ice_servers()` reads STATIC values, once, at lifespan startup — so the
`TURN_USERNAME` / `TURN_CREDENTIAL` fields shipped alongside this spec cannot
carry Cloudflare credentials.

The change is small but it is real, and it has a lifetime problem attached: ICE
servers are currently built ONCE at boot (`main.py:423`) and handed to
`SmallWebRTCRequestHandler`, while minted credentials expire. Whichever of these
the plan picks must be a deliberate choice:

  * mint per WebRTC offer — always fresh, one extra API call per session;
  * mint at boot with a long TTL and refresh on a timer — fewer calls, but a
    stale credential silently breaks every new call until the refresh fires, and
    "silently breaks" is this codebase's recurring failure shape.

Per-offer is the safer default. The TTL must in any case exceed the longest
expected call, or media dies mid-interview.

Settings will therefore be `TURN_KEY_ID` + `TURN_API_TOKEN` for Cloudflare,
with the existing static `TURN_SERVER_URL`/`USERNAME`/`CREDENTIAL` retained for
static-credential providers. Both paths should stay supported: the static one is
what makes coturn or metered.ca a zero-code fallback if Cloudflare disappoints.
- ✅ **Done in this session:** `TURN_SERVER_URL`, `TURN_USERNAME` and
  `TURN_CREDENTIAL` are now in `.env.example` and in the settings UI's Voice
  group. They previously existed in `voice-agent/src/config.py` but had nowhere
  to be entered — Cloudflare credentials would have had no home.

## Design

```
                    Cloudflare
  Recall / Claude ──► Tunnel ──► caddy:80 ─┬─ /api/*         -> backend:8004
                    (outbound;             ├─ /voice-ws-v2/* -> voice-agent:8011
                     no open ports)        ├─ /mcp/*         -> cortex-mcp:8020
                                           └─ /*             -> voice-frontend:3003

  media:  Recall browser ──► Cloudflare TURN ◄── voice-agent
          (both sides connect OUTBOUND; NAT is irrelevant)
```

The settings UI gains a **Public access** section showing the live tunnel
hostname and the three derived URLs to copy — `WEBHOOK_BASE_URL`,
`VOICE_AGENT_URL`, and the MCP URL for Claude — plus the manual steps that cannot
be automated (pasting the webhook URL into the Recall portal, adding the MCP
connector in Claude).

## Verify before building

This session found four things that contradicted the obvious explanation, so the
plan's first task is measurement, not code:

1. **Does aiortc actually offer relay candidates?** `_build_ice_servers()` passes
   TURN to aiortc via aioice. Confirm a relay candidate appears in the SDP with
   real credentials before assuming the plumbing works end to end.
2. **Does Recall's browser accept a relay-only path?** It presumably has good
   connectivity, but the bot variant (`web_4_core`) is a specific runtime.
3. **Does `voice-frontend`'s same-origin status URL survive the proxy?** Its
   `getStatusUrl` uses `window.location.host` off localhost, so behind Caddy it
   resolves to the tunnel host — which must route `/api/*` to the backend. That
   is why `/api/*` is in the routing table.
4. **Does Cloudflare Tunnel's free tier permit this traffic shape?** Long-lived
   WebRTC signalling is HTTP, so it should — confirm rather than assume.

## Out of scope

- Automating the Recall portal step. It is a manual paste; the UI guides it.
- Automating the Claude connector. Same.
- Replacing the absent `deploy-config/` production topology. Caddy here targets
  the local/self-host path only.
