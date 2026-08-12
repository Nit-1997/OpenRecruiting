"""The composite fields.

These exist because every failure they prevent has already happened here: a
localhost issuer advertised to a remote MCP client, an audience allowlist missing
the host so the backend rejected its own freshly minted token, and a Supabase
publishable key set under one of its two names.
"""

import pytest

from app import derive
from app.varmap import all_variables


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("or.example.ai", "https://or.example.ai"),
        ("  or.example.ai  ", "https://or.example.ai"),
        ("https://or.example.ai", "https://or.example.ai"),
        ("https://or.example.ai/", "https://or.example.ai"),
        ("https://or.example.ai///", "https://or.example.ai"),
        # An explicit scheme survives: http is correct for localhost, and
        # upgrading it would break exactly the local case it is used for.
        ("http://localhost:8004", "http://localhost:8004"),
        # A port is part of the address, not decoration.
        ("example.ai:8443", "https://example.ai:8443"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_host(raw, expected):
    assert derive.normalize_host(raw) == expected


def test_expand_writes_every_derived_name():
    out = derive.expand_public_host("or.example.ai")
    assert set(out) == set(derive.PUBLIC_HOST_DERIVED)


def test_expand_shapes_each_kind_of_value():
    out = derive.expand_public_host("or.example.ai")
    host = "https://or.example.ai"
    assert out["WEBHOOK_BASE_URL"] == host
    assert out["VOICE_AGENT_URL"] == host
    assert out["CORTEX_PUBLIC_URL"] == host
    # These two must be equal or the MCP handshake fails on one side only.
    assert out["MCP_JWT_ISSUER"] == out["OIDC_ISSUER"] == host
    # cortex-mcp must stay in the list: internal service tokens (intake prefill)
    # carry aud=cortex-mcp, so dropping it trades one broken flow for another.
    assert out["MCP_ALLOWED_AUDIENCES"] == f"cortex-mcp,{host}"
    assert out["OIDC_AUDIENCE"] == out["MCP_ALLOWED_AUDIENCES"]
    assert out["NEXT_PUBLIC_CORTEX_MCP_URL"] == f"{host}/mcp"


def test_blank_host_writes_nothing():
    """Clearing the field must not blank eight settings."""
    assert derive.expand_public_host("") == {}


def test_expansion_round_trips():
    host, drift = derive.host_from_env(derive.expand_public_host("or.example.ai"))
    assert host == "https://or.example.ai"
    assert drift == []


def test_drift_names_the_stragglers():
    """The exact state this repo shipped in: some values public, some localhost."""
    env = derive.expand_public_host("or.example.ai")
    env["OIDC_ISSUER"] = "http://localhost:8004"
    env["MCP_ALLOWED_AUDIENCES"] = "cortex-mcp"  # host missing entirely
    host, drift = derive.host_from_env(env)
    assert host == "https://or.example.ai"
    assert drift == ["MCP_ALLOWED_AUDIENCES", "OIDC_ISSUER"]


def test_unset_counts_as_drift():
    """An unset issuer is as broken as a wrong one, and harder to notice."""
    env = derive.expand_public_host("or.example.ai")
    del env["CORTEX_PUBLIC_URL"]
    _, drift = derive.host_from_env(env)
    assert "CORTEX_PUBLIC_URL" in drift


def test_a_fully_empty_env_is_not_reported_as_drift():
    """Nothing configured yet is a starting point, not an inconsistency."""
    assert derive.host_from_env({}) == ("", [])


def test_an_extra_hand_added_audience_does_not_confuse_the_reading():
    env = derive.expand_public_host("or.example.ai")
    env["OIDC_AUDIENCE"] += ",https://someone-elses-host"
    host, drift = derive.host_from_env(env)
    assert host == "https://or.example.ai"
    assert drift == []


def test_expand_changes_replaces_the_pseudo_field():
    out = derive.expand_changes({derive.PUBLIC_BASE_URL: "or.example.ai"})
    assert derive.PUBLIC_BASE_URL not in out
    assert out["OIDC_ISSUER"] == "https://or.example.ai"


def test_expand_changes_leaves_ordinary_settings_alone():
    out = derive.expand_changes({"RECALL_BOT_NAME": "Scout"})
    assert out == {"RECALL_BOT_NAME": "Scout"}


def test_mirrors_are_written_with_their_source():
    out = derive.expand_changes({"SUPABASE_URL": "https://p.supabase.co"})
    assert out["NEXT_PUBLIC_SUPABASE_URL"] == "https://p.supabase.co"

    out = derive.expand_changes({"NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY": "sb_pub_x"})
    assert out["NEXT_PUBLIC_SUPABASE_ANON_KEY"] == "sb_pub_x"


def test_every_derived_name_is_a_real_managed_variable():
    """The pseudo-field is not a variable, but everything it writes must be —
    otherwise /api/apply rejects the save as unknown, or writes a name no
    service restarts for."""
    assert derive.DERIVED_NAMES <= all_variables()
    assert derive.PUBLIC_BASE_URL not in all_variables()


def test_derived_values_are_never_also_editable_fields():
    """One writable copy per value. Two is the drift being designed out."""
    from app.varmap import GROUPS

    editable = {
        v.name
        for g in GROUPS
        if g.tier != "internal"
        for v in g.variables
    }
    assert derive.DERIVED_NAMES & editable == set()
