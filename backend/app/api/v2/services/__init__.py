"""Business-logic services for the v2 API.

Each module owns one bounded responsibility (roles, plan, pipeline, ...).
Functions take `supabase` as the first argument; they raise V2DomainError
subclasses on failure — never HTTPException.
"""
