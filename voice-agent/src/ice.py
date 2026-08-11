"""ICE servers for WebRTC, including Cloudflare's ephemeral TURN credentials.

WHY TURN MATTERS HERE. Browser-to-agent voice works without it: both peers are
on the same machine or the same LAN. A Recall meeting bot is not — it runs in
Recall's cloud, and its media is UDP, which no HTTP tunnel carries. This used to
work because the agent had a public IP with UDP 40000-40010 open; behind NAT
there is no such path. A TURN relay fixes it because BOTH peers connect
OUTBOUND to it, so NAT stops mattering.

WHY THIS IS CODE AND NOT JUST CONFIG. Cloudflare TURN does not issue long-term
credentials. You hold a TURN key server-side and mint short-lived
username/password pairs from its API. Static TURN_USERNAME / TURN_CREDENTIAL
settings cannot carry them, which is why this module exists.

Two providers are supported on purpose:

  * Cloudflare — CLOUDFLARE_TURN_TOKEN_ID + CLOUDFLARE_TURN_API_TOKEN, minted.
  * anything with static credentials (coturn, metered.ca) — TURN_SERVER_URL +
    TURN_USERNAME + TURN_CREDENTIAL, used as-is.

Keeping the static path is what makes a different relay a zero-code swap if
Cloudflare ever disappoints.

CREDENTIALS ARE MINTED PER OFFER, not once at boot. Minting at startup and
refreshing on a timer was the alternative, and it fails the wrong way: an
expired credential breaks every NEW call silently until the refresh fires, which
is this codebase's recurring failure shape. A short cache below keeps the API
call off the hot path without ever serving something close to expiry.

A minting failure degrades to STUN-only and says so LOUDLY. Browser voice keeps
working; meeting-bot voice does not. That must be one obvious log line, not a
mystery about why the bot joined and stayed silent.
"""

from __future__ import annotations

import time

import httpx
# aiortc's RTCIceServer, not pipecat's IceServer: this is what main.py already
# handed to SmallWebRTCRequestHandler, and pipecat.transports.smallwebrtc is
# stubbed as a non-package by tests/screening/conftest.py, so importing a
# submodule of it breaks collection for the whole suite.
from aiortc import RTCIceServer

from src.config import get_settings
from src.logging_config import get_logger

logger = get_logger(__name__)

_MINT_URL = "https://rtc.live.cloudflare.com/v1/turn/keys/{key_id}/credentials/generate-ice-servers"
# Long enough to outlast any interview — media dies mid-call if a credential
# expires while the call is up, and the 30-minute session cap plus overrun is
# the number to beat.
_TTL_SECONDS = 24 * 60 * 60
# Re-mint well before expiry so a cached credential is never near the edge.
_REFRESH_MARGIN_SECONDS = 60 * 60
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_cache: tuple[float, list[RTCIceServer]] | None = None


def _stun_only() -> list[RTCIceServer]:
    settings = get_settings()
    return [RTCIceServer(urls=url) for url in settings.ice_stun_servers]


def _static_turn() -> list[RTCIceServer] | None:
    """A non-Cloudflare relay configured with long-term credentials."""
    settings = get_settings()
    if not settings.turn_server_url:
        return None
    return _stun_only() + [
        RTCIceServer(
            urls=settings.turn_server_url,
            username=settings.turn_username,
            credential=settings.turn_credential,
        )
    ]


async def _mint_cloudflare() -> list[RTCIceServer] | None:
    """Short-lived Cloudflare TURN credentials, or None if unavailable."""
    settings = get_settings()
    key_id = settings.cloudflare_turn_token_id
    api_token = settings.cloudflare_turn_api_token
    if not key_id or not api_token:
        return None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _MINT_URL.format(key_id=key_id),
                headers={"Authorization": f"Bearer {api_token}"},
                json={"ttl": _TTL_SECONDS},
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("turn_mint_failed", extra={
            "event": "turn_mint_failed",
            "error": str(exc),
            "detail": (
                "Could not mint Cloudflare TURN credentials. Falling back to "
                "STUN only: browser voice still works, but a Recall meeting bot "
                "will connect and stay SILENT because its media cannot traverse "
                "NAT without a relay."
            ),
        })
        return None

    # The response is a LIST: entry 0 is STUN-only, entry 1 carries the TURN
    # urls plus username/credential. Reading [0] yields a credential-less STUN
    # block that looks like a successful mint — a mistake worth naming here.
    servers: list[RTCIceServer] = []
    for entry in payload.get("iceServers") or []:
        urls = entry.get("urls") or []
        urls = [urls] if isinstance(urls, str) else urls
        username, credential = entry.get("username"), entry.get("credential")
        for url in urls:
            if username and credential:
                servers.append(RTCIceServer(urls=url, username=username, credential=credential))
            else:
                servers.append(RTCIceServer(urls=url))

    if not any(s.username for s in servers):
        logger.error("turn_mint_returned_no_credentials", extra={
            "event": "turn_mint_returned_no_credentials",
            "detail": (
                "Cloudflare accepted the request but returned no TURN username. "
                "Check the API token has TURN permissions on this key."
            ),
        })
        return None

    logger.info("turn_credentials_minted", extra={
        "event": "turn_credentials_minted",
        "relay_urls": sum(1 for s in servers if s.username),
        "ttl_seconds": _TTL_SECONDS,
    })
    return servers


async def get_ice_servers() -> list[RTCIceServer]:
    """STUN plus a TURN relay when one is configured.

    Cached until shortly before the minted credentials expire, so a busy
    instance does not call the mint API on every offer while still never
    handing out something near its expiry.
    """
    global _cache

    static = _static_turn()
    if static is not None:
        return static

    now = time.time()
    if _cache and now < _cache[0]:
        return _cache[1]

    minted = await _mint_cloudflare()
    if minted is None:
        # Not cached: retry on the next offer rather than pinning a degraded
        # config until restart.
        return _stun_only()

    _cache = (now + _TTL_SECONDS - _REFRESH_MARGIN_SECONDS, minted)
    return minted


def reset_cache() -> None:
    """Test seam."""
    global _cache
    _cache = None
