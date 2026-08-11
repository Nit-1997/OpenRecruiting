"""The .env writer must not mangle a file people still hand-edit.

.env.example carries 95 comment lines documenting what each setting does. A
writer that serialises a dict back out would delete all of them, which is a
worse outcome than never having built the UI.
"""

import os

import pytest

from app.envfile import atomic_write, parse, update

SAMPLE = """\
# ── Database ─────────────────────────────────
# Create a free project at supabase.com
SUPABASE_URL=https://old.supabase.co
SUPABASE_SECRET_KEY=old-secret

# Voice
VOICE_DEEPGRAM_API_KEY=

# A value containing an equals sign and a hash
TRICKY=a=b#not-a-comment
QUOTED="keep the quotes"
"""


def test_parse_reads_values_and_ignores_comments():
    values = parse(SAMPLE)

    assert values["SUPABASE_URL"] == "https://old.supabase.co"
    assert values["VOICE_DEEPGRAM_API_KEY"] == ""
    assert "# Voice" not in values


def test_a_value_may_contain_equals_and_hash():
    """Splitting on every '=' or stripping everything after '#' would corrupt
    real values — API keys and DSNs contain both."""
    assert parse(SAMPLE)["TRICKY"] == "a=b#not-a-comment"


def test_quotes_are_preserved_verbatim():
    """Docker compose treats quotes literally in env_file, so stripping them
    would silently change the value the container receives."""
    assert parse(SAMPLE)["QUOTED"] == '"keep the quotes"'


def test_update_preserves_every_comment_and_the_key_order():
    out = update(SAMPLE, {"SUPABASE_URL": "https://new.supabase.co"})

    assert "# ── Database ─────────────────────────────────" in out
    assert "# Create a free project at supabase.com" in out
    assert "# Voice" in out
    assert out.index("SUPABASE_URL") < out.index("SUPABASE_SECRET_KEY") < out.index("VOICE_DEEPGRAM_API_KEY")


def test_update_changes_only_the_targeted_line():
    out = update(SAMPLE, {"SUPABASE_URL": "https://new.supabase.co"})

    changed = [
        (a, b)
        for a, b in zip(SAMPLE.splitlines(), out.splitlines())
        if a != b
    ]
    assert changed == [
        ("SUPABASE_URL=https://old.supabase.co", "SUPABASE_URL=https://new.supabase.co")
    ]


def test_a_new_key_is_appended_rather_than_reordering_the_file():
    out = update(SAMPLE, {"BRAND_NEW_KEY": "value"})

    assert out.splitlines()[-1] == "BRAND_NEW_KEY=value"
    assert out.startswith("# ── Database")


def test_an_empty_value_is_written_as_an_empty_assignment():
    """Clearing a secret must leave the key present and blank, not delete the
    line — a missing key reads as 'never configured' in the UI, and the comment
    above it would lose its subject."""
    out = update(SAMPLE, {"SUPABASE_SECRET_KEY": ""})

    assert "SUPABASE_SECRET_KEY=" in out
    assert parse(out)["SUPABASE_SECRET_KEY"] == ""


def test_atomic_write_leaves_a_timestamped_backup(tmp_path):
    target = tmp_path / ".env"
    target.write_text(SAMPLE, encoding="utf-8")

    atomic_write(target, "NEW=1\n")

    assert target.read_text(encoding="utf-8") == "NEW=1\n"
    backups = list(tmp_path.glob(".env.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == SAMPLE


def test_atomic_write_does_not_leave_a_partial_file_on_failure(tmp_path, monkeypatch):
    """A half-written .env bricks every container on the next restart. The
    temp-file + rename dance is the whole point, so it is tested rather than
    assumed."""
    target = tmp_path / ".env"
    target.write_text(SAMPLE, encoding="utf-8")

    real_replace = os.replace

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write(target, "NEW=1\n")
    monkeypatch.setattr(os, "replace", real_replace)

    assert target.read_text(encoding="utf-8") == SAMPLE
    assert list(tmp_path.glob("*.tmp")) == []
