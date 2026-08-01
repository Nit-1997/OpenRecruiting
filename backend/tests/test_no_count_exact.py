import os
import subprocess

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_count_exact_in_repo():
    """The custom Supabase TableClient.select() has no `count` kwarg and
    TableResponse has no `.count`. Forbid the broken `count="exact"` pattern;
    use `await ....count_async()` instead."""
    out = subprocess.run(
        ["grep", "-rn", 'count="exact"', "app"],
        cwd=_BACKEND_ROOT,
        capture_output=True,
        text=True,
    ).stdout
    assert out.strip() == "", f'count="exact" is forbidden:\n{out}'
