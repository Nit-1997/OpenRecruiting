"""The variable map is the whole restart-scoping mechanism.

If a variable is missing from it, saving that variable restarts nothing and the
UI reports success — the exact "looks applied, isn't" failure this project keeps
producing. The completeness test below is the guard against that.
"""

from pathlib import Path

import pytest
import yaml

from app.envfile import parse
from app.varmap import GROUPS, affected_services, all_variables, is_secret

REPO = Path(__file__).resolve().parents[2]


def _example_keys() -> set[str]:
    example = REPO / ".env.example"
    if not example.exists():
        pytest.skip(".env.example not reachable from this checkout")
    return set(parse(example.read_text(encoding="utf-8")))


def test_every_variable_in_env_example_is_mapped():
    """A new variable must not silently become unmanaged. Adding one to
    .env.example without adding it here fails right there."""
    unmapped = _example_keys() - all_variables()

    assert unmapped == set(), (
        f"these .env.example variables are in no group, so the UI would neither "
        f"show them nor know what to restart: {sorted(unmapped)}"
    )


def test_the_map_does_not_invent_variables():
    """The reverse direction. A typo'd key here would render a field that
    writes a variable nothing reads."""
    example = _example_keys()
    invented = all_variables() - example

    assert invented == set(), f"not present in .env.example: {sorted(invented)}"


def test_every_service_named_in_the_map_exists_in_compose():
    """A restart target that is not a real service would fail at apply time,
    after the file had already been written."""
    compose = REPO / "docker-compose.yml"
    if not compose.exists():
        pytest.skip("docker-compose.yml not reachable")
    services = set(yaml.safe_load(compose.read_text(encoding="utf-8"))["services"])

    named = {svc for group in GROUPS for var in group.variables for svc in var.services}

    assert named <= services, f"unknown services: {sorted(named - services)}"


def test_secrets_are_marked_so_the_api_never_returns_them():
    """Write-only handling is driven off this flag. A key that looks like a
    credential but is not flagged would be echoed back to the browser."""
    for group in GROUPS:
        for var in group.variables:
            looks_secret = any(
                token in var.name for token in ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")
            )
            # A name ending in _URL is an ADDRESS, not a credential —
            # CORTEX_TOKEN_URL is where tokens are issued, not a token. And
            # PUBLISHABLE/ANON keys are designed to ship to browsers, so hiding
            # them would make the UI unable to show a value the page source
            # already contains.
            # _URL is an ADDRESS and _KEY_ID is an IDENTIFIER, neither is a
            # credential: CORTEX_TOKEN_URL is where tokens are issued, and
            # MCP_JWT_KEY_ID is the `kid` that gets published in JWKS.
            if (
                var.name.endswith("_URL")
                or var.name.endswith("_KEY_ID")
                or "PUBLISHABLE" in var.name
                or "ANON" in var.name
            ):
                continue
            if looks_secret:
                assert var.secret, f"{var.name} looks like a credential but is not marked secret"


def test_affected_services_are_deduplicated_and_sorted():
    result = affected_services(["SUPABASE_URL", "SUPABASE_SECRET_KEY"])

    assert result == sorted(set(result))
    assert "backend" in result


def test_an_unknown_variable_affects_nothing_rather_than_everything():
    """Fail closed on the restart side: an unrecognised key must not trigger a
    full-stack bounce."""
    assert affected_services(["NOT_A_REAL_VARIABLE"]) == []


def test_is_secret_matches_the_group_definitions():
    assert is_secret("SUPABASE_SECRET_KEY") is True
    assert is_secret("SUPABASE_URL") is False
