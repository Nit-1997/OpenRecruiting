"""Read and write `.env` without destroying it.

The file stays the source of truth and stays hand-editable — `.env.example`
carries 95 comment lines explaining what each setting does, and a self-hoster is
still expected to be able to open, read, diff and `cat` the real thing. So this
module edits LINES rather than round-tripping a dict: an unrelated line is
returned byte-identical, and only the assignments actually being changed move.

Writes go through a temp file and `os.replace`, which is atomic on POSIX. A
half-written `.env` would take down every container on its next restart, which
is a considerably worse failure than refusing to save.
"""

from __future__ import annotations

import os
import time
from pathlib import Path


def _split(line: str) -> tuple[str, str] | None:
    """`KEY=value` → (key, value), or None if the line is not an assignment.

    Splits on the FIRST `=` only and never strips a trailing comment: real
    values (API keys, DSNs, connection strings) routinely contain both `=` and
    `#`, and treating those as syntax silently corrupts them.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    key = key.strip()
    if not key or not all(c.isalnum() or c == "_" for c in key):
        return None
    return key, value


def parse(text: str) -> dict[str, str]:
    """Every assignment in the file. Later duplicates win, matching how
    docker-compose reads env files."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        pair = _split(line)
        if pair:
            values[pair[0]] = pair[1]
    return values


def update(text: str, changes: dict[str, str]) -> str:
    """Apply `changes`, preserving comments, blank lines and key order.

    Keys already present are edited in place. Keys that are new are appended.
    An empty string writes `KEY=`, which is deliberate: deleting the line would
    orphan the comment above it and make a cleared setting indistinguishable
    from one that never existed.
    """
    remaining = dict(changes)
    out: list[str] = []
    trailing_newline = text.endswith("\n")

    for line in text.splitlines():
        pair = _split(line)
        if pair and pair[0] in remaining:
            key = pair[0]
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)

    for key, value in remaining.items():
        out.append(f"{key}={value}")

    result = "\n".join(out)
    return result + "\n" if trailing_newline or remaining else result


def atomic_write(path: str | Path, text: str) -> Path | None:
    """Write `text` to `path` atomically, leaving a timestamped backup.

    Returns the backup path, or None when there was no prior file. The temp file
    is removed on failure so a crashed save never leaves debris next to a config
    file the whole stack reads.
    """
    path = Path(path)
    backup: Path | None = None
    if path.exists():
        backup = path.with_name(f"{path.name}.bak.{int(time.time())}")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return backup
