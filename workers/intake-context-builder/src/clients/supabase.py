"""Supabase client wrapper for the Lambda."""

from __future__ import annotations

from typing import Optional

from supabase import Client, create_client

_client: Optional[Client] = None


def get_supabase_client(url: str, key: str) -> Client:
    global _client
    if _client is None:
        _client = create_client(url, key)
    return _client


def close_supabase_client() -> None:
    """Called from pipeline.run_pipeline's finally block. Resets module global."""
    global _client
    _client = None
