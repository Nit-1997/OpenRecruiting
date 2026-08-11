"""The variable map is the whole restart-scoping mechanism.

If a variable is missing from it, saving that variable restarts nothing and the
UI reports success — the exact "looks applied, isn't" failure this project keeps
producing. The completeness test below is the guard against that.
"""

from pathlib import Path

import pytest
import yaml

from app.envfile import parse
from app.varmap import GROUPS, UNMANAGED, affected_services, all_variables, is_secret

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


def _backend_settings() -> set[str]:
    """Every UPPER_CASE field on the backend Settings class."""
    import re

    cfg = REPO / "backend" / "app" / "config.py"
    if not cfg.exists():
        pytest.skip("backend/app/config.py not reachable")
    return set(re.findall(r"^\s{4}([A-Z][A-Z0-9_]+)\s*:", cfg.read_text(encoding="utf-8"), re.M))


def test_every_backend_setting_is_either_managed_or_explicitly_excluded():
    """The guard that .env.example could not provide.

    The first version of this map was built from .env.example and silently
    omitted the entire Email group — eight settings including RESEND_API_KEY,
    ZEPTOMAIL_API_TOKEN and two more keys — because that file documents only 21
    of the backend's 101 settings. Nothing failed; the fields simply were not
    there, and it took someone asking "why is there no Resend key" to find it.

    Reading the Settings class instead makes the omission impossible: a new
    backend setting must be given a group or an explicit reason for not having
    one.
    """
    unaccounted = sorted(_backend_settings() - all_variables() - set(UNMANAGED))

    assert unaccounted == [], (
        "these backend settings are neither in a UI group nor in UNMANAGED. Add "
        f"them to one or the other — silence is how a credential goes missing: {unaccounted}"
    )


def test_every_exclusion_carries_a_reason():
    """An UNMANAGED entry with an empty reason is the same unexplained gap in a
    different place."""
    blank = sorted(name for name, reason in UNMANAGED.items() if not reason.strip())

    assert blank == []


def test_nothing_is_both_managed_and_excluded():
    overlap = sorted(all_variables() & set(UNMANAGED))

    assert overlap == []


def _backend_defaults() -> dict[str, str]:
    """Literal defaults on the backend Settings class, as written."""
    import re

    cfg = REPO / "backend" / "app" / "config.py"
    if not cfg.exists():
        pytest.skip("backend/app/config.py not reachable")
    out: dict[str, str] = {}
    for name, raw in re.findall(
        r"^\s{4}([A-Z][A-Z0-9_]+)\s*:[^=\n]+=\s*([^\n#]+)", cfg.read_text(encoding="utf-8"), re.M
    ):
        out[name] = raw.strip().strip('"').strip("'").strip()
    return out


def test_env_example_never_contradicts_a_real_default():
    """.env.example is what a new self-hoster copies, so a value there that
    disagrees with the code silently changes behaviour on a fresh install.

    This exists because it happened: ATS_INTEGRATIONS_ENABLED=false was written
    into .env.example while the Settings default is True, which would have
    turned ATS sync off for everyone who followed the quick start — with nothing
    failing and nothing to notice.

    Compared only where BOTH sides are non-empty. A blank in .env.example
    (`KEY=`) is an invitation to fill something in, and an empty default in the
    code means it has no opinion — so a placeholder like
    INTERNAL_API_SECRET=change-me-local-only is guidance, not a contradiction.
    The failure this catches is a real default being silently overridden.
    """
    defaults = _backend_defaults()
    example = parse((REPO / ".env.example").read_text(encoding="utf-8"))

    mismatches = {
        key: (value, defaults[key])
        for key, value in example.items()
        if value and defaults.get(key) and value.lower() != defaults[key].lower()
    }

    assert mismatches == {}, (
        "these .env.example values disagree with backend/app/config.py "
        f"(example, actual): {mismatches}"
    )
