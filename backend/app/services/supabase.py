"""Custom PostgREST client for backend.

NOTE: the module-global `_async_client` (httpx.AsyncClient) is cached for the
long-lived uvicorn process and is safe there. It MUST NOT be imported or reused
inside any AWS Lambda handler — warm-container reuse binds it to a dead asyncio
event loop and fails with "Event loop is closed" (see CLAUDE.md async-resource
rules). Lambdas must construct + tear down their own async clients per invocation.
"""

import json
import time

import httpx
from app.config import get_settings
from app.logging_config import (
    correlation_id_var,
    get_logger,
    request_id_var,
)
from functools import lru_cache
from contextlib import asynccontextmanager
from typing import Optional
import asyncio

logger = get_logger(__name__)


async def _inject_request_id_header(request: httpx.Request) -> None:
    """httpx async event_hook — copies the current request_id (and
    correlation_id, if present) into outbound headers so downstream services
    can correlate their logs with the inbound request that triggered them.

    No-op when called outside a request context (e.g. background tasks
    without a request_id set)."""
    rid = request_id_var.get()
    if rid:
        request.headers["X-Request-ID"] = rid
    cid = correlation_id_var.get()
    if cid:
        request.headers["X-Correlation-ID"] = cid


class RpcError(Exception):
    """Raised by SupabaseAdminClient.rpc when PostgREST returns a non-2xx.

    Exposes the Postgres SQLSTATE (in `code`) and the RAISE message so handlers
    can map RPC failures to specific HTTP status codes (e.g. P0002 -> 404,
    P0001 with message 'LAST_ROUND' -> 409). Fields mirror the PostgREST error
    JSON shape: {code, message, details, hint}.
    """

    def __init__(self, message: str, code: Optional[str] = None,
                 details: Optional[str] = None, hint: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.hint = hint


class PostgrestError(RpcError):
    """Raised by Insert/Update/Delete/Upsert builders when PostgREST returns
    a non-2xx. Same shape as RpcError so callers that already catch
    RpcError keep working; the distinct type lets services match on
    SQLSTATE without confusing table errors with RPC errors.

    SQLSTATE values that callers typically branch on:
      - '23505' unique_violation
      - '23503' foreign_key_violation
      - '23514' check_violation
      - '42P01' undefined_table
    """


def _build_postgrest_error(response: httpx.Response, default_msg: str) -> "PostgrestError":
    """Parse a PostgREST error response into PostgrestError. Falls back to
    the default message + a stringified status when the body isn't JSON or
    lacks the expected fields."""
    try:
        payload = response.json() if response.content else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    message = (
        payload.get("message")
        or payload.get("details")
        or payload.get("msg")
        or default_msg
    )
    return PostgrestError(
        message=str(message),
        code=payload.get("code"),
        details=payload.get("details"),
        hint=payload.get("hint"),
    )


def _is_single_no_rows(response: httpx.Response) -> bool:
    """True when a `.single()` read returned PostgREST's "zero rows" signal.

    PostgREST returns code `PGRST116` (HTTP 406) when a singular response is
    requested but no rows match. That is a legitimate empty result the codebase
    treats as `None`, NOT a DB/network error — so reads must not raise on it.
    """
    try:
        payload = response.json() if response.content else {}
    except Exception:
        return False
    return isinstance(payload, dict) and payload.get("code") == "PGRST116"


# Persistent HTTP clients with connection pooling
_sync_client: Optional[httpx.Client] = None
_async_client: Optional[httpx.AsyncClient] = None


def _apply_filters_to_params(
    params: dict[str, str],
    filters: list[tuple[str, str, str]],
) -> None:
    """Apply PostgREST filters; preserve multiple predicates on same column.

    PostgREST query strings can't express duplicate keys with a plain dict
    (`event_start=gt...` and `event_start=lte...`) because later assignments
    overwrite earlier ones. When duplicate columns are present, collapse all
    predicates into a single explicit `and=(...)` clause.
    """
    if not filters:
        return

    counts: dict[str, int] = {}
    for col, _, _ in filters:
        counts[col] = counts.get(col, 0) + 1

    has_duplicates = any(v > 1 for v in counts.values())
    if has_duplicates:
        predicates = [f"{col}.{op}.{val}" for col, op, val in filters]
        params["and"] = f"({','.join(predicates)})"
        return

    for col, op, val in filters:
        params[col] = f"{op}.{val}"


def _apply_or_groups(params: dict, groups: list[str]) -> None:
    """Render collected `or_filter` groups onto the params dict.

    One group → `or=(...)`; several → ANDed `and=(or(g1),or(g2))` (PostgREST
    can't carry two top-level `or` params). When `_apply_filters_to_params`
    already produced an `and=(...)` clause for duplicate columns, splice the
    groups into it instead of overwriting."""
    if not groups:
        return
    if len(groups) == 1:
        params["or"] = f"({groups[0]})"
        return
    rendered = ",".join(f"or({g})" for g in groups)
    existing_and = params.get("and")
    if existing_and:
        params["and"] = f"({existing_and[1:-1]},{rendered})"
    else:
        params["and"] = f"({rendered})"


def get_sync_http_client() -> httpx.Client:
    global _sync_client
    if _sync_client is None or _sync_client.is_closed:
        _sync_client = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _sync_client


def get_async_http_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None or _async_client.is_closed:
        _async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            event_hooks={"request": [_inject_request_id_header]},
        )
    return _async_client


class SupabaseAdminClient:
    def __init__(self, url: str, secret_key: str):
        self.url = url
        self.secret_key = secret_key
        self.headers = {
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        }

    def table(self, table_name: str) -> "TableClient":
        return TableClient(self, table_name)

    async def invite_user_by_email(self, email: str, redirect_to: str, data: dict | None = None) -> dict:
        client = get_async_http_client()
        body = {"email": email}
        if data:
            body["data"] = data

        response = await client.post(
            f"{self.url}/auth/v1/invite",
            json=body,
            headers=self.headers,
            params={"redirect_to": redirect_to} if redirect_to else {},
        )
        if response.status_code not in (200, 201):
            error = response.json()
            raise Exception(error.get("message", error.get("msg", "Failed to invite user")))
        return response.json()

    async def delete_user(self, user_id: str) -> bool:
        client = get_async_http_client()
        response = await client.delete(
            f"{self.url}/auth/v1/admin/users/{user_id}",
            headers=self.headers,
        )
        if response.status_code not in (200, 204):
            error = response.json() if response.content else {}
            raise Exception(error.get("message", error.get("msg", "Failed to delete user")))
        return True

    async def get_auth_user(self, user_id: str) -> dict | None:
        client = get_async_http_client()
        response = await client.get(
            f"{self.url}/auth/v1/admin/users/{user_id}",
            headers=self.headers,
        )
        if response.status_code == 200:
            return response.json()
        return None

    async def get_auth_users_batch(self, user_ids: list[str]) -> dict[str, dict]:
        client = get_async_http_client()
        tasks = [
            client.get(f"{self.url}/auth/v1/admin/users/{uid}", headers=self.headers)
            for uid in user_ids
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        result = {}
        for uid, resp in zip(user_ids, responses):
            if not isinstance(resp, Exception) and resp.status_code == 200:
                result[uid] = resp.json()
        return result

    async def ban_user(self, user_id: str, ban: bool = True) -> bool:
        client = get_async_http_client()
        response = await client.put(
            f"{self.url}/auth/v1/admin/users/{user_id}",
            headers=self.headers,
            json={"ban_duration": "876600h" if ban else "none"}
        )
        if response.status_code not in (200, 201):
            error = response.json() if response.content else {}
            raise Exception(error.get("message", error.get("msg", "Failed to ban user")))
        return True

    async def ban_users_batch(self, user_ids: list[str], ban: bool = True) -> bool:
        client = get_async_http_client()
        tasks = [
            client.put(
                f"{self.url}/auth/v1/admin/users/{user_id}",
                headers=self.headers,
                json={"ban_duration": "876600h" if ban else "none"}
            )
            for user_id in user_ids
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        return True

    async def rpc(self, function_name: str, params: dict) -> "TableResponse":
        client = get_async_http_client()
        response = await client.post(
            f"{self.url}/rest/v1/rpc/{function_name}",
            json=params,
            headers=self.headers,
        )
        if response.status_code == 204:
            # PostgREST returns 204 No Content for RETURNS VOID functions.
            return TableResponse(data=None)
        if response.status_code in (200, 201):
            return TableResponse(response.json())
        error = response.json() if response.content else {}
        # Surface PostgREST error details so handlers can map SQLSTATE -> HTTP.
        raise RpcError(
            message=error.get("message", error.get("msg", f"RPC {function_name} failed")),
            code=error.get("code"),
            details=error.get("details"),
            hint=error.get("hint"),
        )


class TableClient:
    def __init__(self, client: SupabaseAdminClient, table_name: str):
        self.client = client
        self.table_name = table_name
        self._select_columns = "*"
        self._filters: list[tuple[str, str, str]] = []
        self._single = False
        self._order_column: Optional[str] = None
        self._order_desc: bool = False
        self._not_null_column: Optional[str] = None
        self._limit: Optional[int] = None
        self._offset: Optional[int] = None
        self._or_filters: list[str] = []

    def select(self, columns: str = "*") -> "TableClient":
        self._select_columns = columns
        return self

    def eq(self, column: str, value: str) -> "TableClient":
        self._filters.append((column, "eq", value))
        return self

    def neq(self, column: str, value: str) -> "TableClient":
        self._filters.append((column, "neq", value))
        return self

    def is_null(self, column: str) -> "TableClient":
        self._filters.append((column, "is", "null"))
        return self

    def is_(self, column: str, value: str) -> "TableClient":
        self._filters.append((column, "is", value))
        return self

    def in_(self, column: str, values: list) -> "TableClient":
        if values:
            values_str = ",".join(str(v) for v in values)
            self._filters.append((column, "in", f"({values_str})"))
        return self

    def lt(self, column: str, value: str) -> "TableClient":
        self._filters.append((column, "lt", value))
        return self

    def gt(self, column: str, value: str) -> "TableClient":
        self._filters.append((column, "gt", value))
        return self

    def lte(self, column: str, value: str) -> "TableClient":
        self._filters.append((column, "lte", value))
        return self

    def gte(self, column: str, value: str) -> "TableClient":
        self._filters.append((column, "gte", value))
        return self

    def not_null(self, column: str) -> "TableClient":
        self._not_null_column = column
        return self

    def order(self, column: str, desc: bool = False) -> "TableClient":
        self._order_column = column
        self._order_desc = desc
        return self

    def limit(self, count: int) -> "TableClient":
        self._limit = count
        return self

    def offset(self, count: int) -> "TableClient":
        self._offset = count
        return self

    def ilike(self, column: str, pattern: str) -> "TableClient":
        self._filters.append((column, "ilike", f"*{pattern}*"))
        return self

    def contains(self, column: str, value) -> "TableClient":
        if isinstance(value, (dict, list)):
            encoded = json.dumps(value, separators=(",", ":"))
        else:
            encoded = str(value)
        self._filters.append((column, "cs", encoded))
        return self

    def or_filter(self, conditions: str) -> "TableClient":
        """Add an OR group. Each call adds an independent group; groups are
        ANDed together (PostgREST: one group → `or=(...)`; several →
        `and=(or(g1),or(g2))`), so e.g. a status-bucket group and a search
        group can coexist on one query."""
        self._or_filters.append(conditions)
        return self

    def _apply_or_filters(self, params: dict) -> None:
        _apply_or_groups(params, self._or_filters)

    def single(self) -> "TableClient":
        self._single = True
        return self

    # DEPRECATED: do not call from async paths
    def execute(self) -> "TableResponse":
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        params = {"select": self._select_columns}

        headers = {**self.client.headers}
        all_filters = list(self._filters)
        if self._not_null_column:
            all_filters.append((self._not_null_column, "not.is", "null"))
        _apply_filters_to_params(params, all_filters)

        if self._order_column:
            params["order"] = f"{self._order_column}.{'desc' if self._order_desc else 'asc'}"

        if self._limit is not None:
            params["limit"] = str(self._limit)

        if self._offset is not None:
            params["offset"] = str(self._offset)

        self._apply_or_filters(params)

        headers["Prefer"] = "return=representation"

        client = get_sync_http_client()
        response = client.get(url, params=params, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if self._single:
                if isinstance(data, list) and len(data) > 0:
                    return TableResponse(data[0])
                elif isinstance(data, list) and len(data) == 0:
                    return TableResponse(None)
                return TableResponse(data)
            else:
                return TableResponse(data if isinstance(data, list) else [data] if data else [])
        return TableResponse([] if not self._single else None)

    async def execute_async(self) -> "TableResponse":
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        params = {"select": self._select_columns}

        headers = {**self.client.headers}
        all_filters = list(self._filters)
        if self._not_null_column:
            all_filters.append((self._not_null_column, "not.is", "null"))
        _apply_filters_to_params(params, all_filters)

        if self._order_column:
            params["order"] = f"{self._order_column}.{'desc' if self._order_desc else 'asc'}"

        if self._limit is not None:
            params["limit"] = str(self._limit)

        if self._offset is not None:
            params["offset"] = str(self._offset)

        self._apply_or_filters(params)

        headers["Prefer"] = "return=representation"

        client = get_async_http_client()
        start = time.monotonic()
        response = await client.get(url, params=params, headers=headers)
        duration_ms = int((time.monotonic() - start) * 1000)
        log_extra = {
            "event": "db_query",
            "table": self.table_name,
            "operation": "select",
            "status": response.status_code,
            "duration_ms": duration_ms,
            "columns": self._select_columns,
        }
        if response.status_code == 200:
            if duration_ms > 200:
                logger.info("db_query", extra=log_extra)
            else:
                logger.debug("db_query", extra=log_extra)
            data = response.json()
            if self._single:
                if isinstance(data, list) and len(data) > 0:
                    return TableResponse(data[0])
                elif isinstance(data, list) and len(data) == 0:
                    return TableResponse(None)
                return TableResponse(data)
            else:
                return TableResponse(data if isinstance(data, list) else [data] if data else [])
        # .single() with zero matching rows is a legitimate empty result, not a
        # DB error: PostgREST signals it with code PGRST116. Preserve the
        # long-standing "no rows -> None" contract that callers branch on
        # (`if not result.data: raise NotFoundError(...)`). All other non-2xx
        # responses (500s, real PostgREST errors) now fail loud.
        if self._single and _is_single_no_rows(response):
            if duration_ms > 200:
                logger.info("db_query", extra=log_extra)
            else:
                logger.debug("db_query", extra=log_extra)
            return TableResponse(None)
        logger.warning("db_query", extra=log_extra)
        raise _build_postgrest_error(response, "Select failed")

    async def count_async(self) -> int:
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        params = {"select": "id"}

        headers = {**self.client.headers}
        all_filters = list(self._filters)
        if self._not_null_column:
            all_filters.append((self._not_null_column, "not.is", "null"))
        _apply_filters_to_params(params, all_filters)

        self._apply_or_filters(params)

        headers["Prefer"] = "count=exact"
        headers["Range-Unit"] = "items"
        headers["Range"] = "0-0"

        client = get_async_http_client()
        response = await client.get(url, params=params, headers=headers)
        if response.status_code >= 400:
            logger.warning(
                "db_query",
                extra={
                    "event": "db_query",
                    "table": self.table_name,
                    "operation": "count",
                    "status": response.status_code,
                },
            )
            raise _build_postgrest_error(response, "Count failed")
        content_range = response.headers.get("content-range", "")
        if "/" in content_range:
            total = content_range.split("/")[1]
            if total != "*":
                return int(total)
        return 0

    def insert(self, data: dict) -> "InsertBuilder":
        return InsertBuilder(self.client, self.table_name, data)

    def upsert(self, data: dict, on_conflict: str = "") -> "UpsertBuilder":
        return UpsertBuilder(self.client, self.table_name, data, on_conflict)

    def update(self, data: dict) -> "UpdateBuilder":
        return UpdateBuilder(self.client, self.table_name, data, self._filters)

    def delete(self) -> "DeleteBuilder":
        return DeleteBuilder(self.client, self.table_name, self._filters)


class InsertBuilder:
    def __init__(self, client: SupabaseAdminClient, table_name: str, data: dict):
        self.client = client
        self.table_name = table_name
        self.data = data

    def execute(self) -> "TableResponse":
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        headers = {
            **self.client.headers,
            "Prefer": "return=representation",
        }

        http_client = get_sync_http_client()
        response = http_client.post(url, json=self.data, headers=headers)
        if response.status_code in (200, 201):
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                return TableResponse(data[0])
            return TableResponse(data)
        raise _build_postgrest_error(response, "Insert failed")

    async def execute_async(self) -> "TableResponse":
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        headers = {
            **self.client.headers,
            "Prefer": "return=representation",
        }

        client = get_async_http_client()
        start = time.monotonic()
        response = await client.post(url, json=self.data, headers=headers)
        duration_ms = int((time.monotonic() - start) * 1000)
        log_extra = {
            "event": "db_query",
            "table": self.table_name,
            "operation": "insert",
            "status": response.status_code,
            "duration_ms": duration_ms,
        }
        if response.status_code in (200, 201):
            if duration_ms > 200:
                logger.info("db_query", extra=log_extra)
            else:
                logger.debug("db_query", extra=log_extra)
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                return TableResponse(data[0])
            return TableResponse(data)
        logger.warning("db_query", extra=log_extra)
        raise _build_postgrest_error(response, "Insert failed")


class UpsertBuilder:
    def __init__(self, client: SupabaseAdminClient, table_name: str, data: dict, on_conflict: str = ""):
        import re
        if on_conflict and not re.match(r'^[a-z_][a-z0-9_]*$', on_conflict):
            raise ValueError(f"Invalid on_conflict column name: {on_conflict}")
        self.client = client
        self.table_name = table_name
        self.data = data
        self.on_conflict = on_conflict

    async def execute_async(self) -> "TableResponse":
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        prefer = "return=representation,resolution=merge-duplicates"
        headers = {
            **self.client.headers,
            "Prefer": prefer,
        }
        if self.on_conflict:
            params = {"on_conflict": self.on_conflict}
        else:
            params = {}

        client = get_async_http_client()
        start = time.monotonic()
        response = await client.post(url, json=self.data, params=params, headers=headers)
        duration_ms = int((time.monotonic() - start) * 1000)
        log_extra = {
            "event": "db_query",
            "table": self.table_name,
            "operation": "upsert",
            "status": response.status_code,
            "duration_ms": duration_ms,
        }
        if response.status_code in (200, 201):
            if duration_ms > 200:
                logger.info("db_query", extra=log_extra)
            else:
                logger.debug("db_query", extra=log_extra)
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                return TableResponse(data[0])
            return TableResponse(data)
        logger.warning("db_query", extra=log_extra)
        raise _build_postgrest_error(response, "Upsert failed")


class InsertManyBuilder:
    def __init__(self, client: SupabaseAdminClient, table_name: str, data: list[dict]):
        self.client = client
        self.table_name = table_name
        self.data = data

    async def execute_async(self) -> "TableResponse":
        if not self.data:
            return TableResponse([])

        url = f"{self.client.url}/rest/v1/{self.table_name}"
        headers = {
            **self.client.headers,
            "Prefer": "return=representation",
        }

        client = get_async_http_client()
        response = await client.post(url, json=self.data, headers=headers)
        if response.status_code in (200, 201):
            data = response.json()
            return TableResponse(data if isinstance(data, list) else [data])
        raise _build_postgrest_error(response, "Insert failed")


class UpdateBuilder:
    def __init__(self, client: SupabaseAdminClient, table_name: str, data: dict, filters: list):
        self.client = client
        self.table_name = table_name
        self.data = data
        self._filters = filters
        self._or_filters: list[str] = []

    def eq(self, column: str, value: str) -> "UpdateBuilder":
        self._filters.append((column, "eq", value))
        return self

    def or_filter(self, conditions: str) -> "UpdateBuilder":
        # PostgREST `or=(...)`; ANDed with the other (eq/neq/...) filters. Needed
        # for NULL-tolerant CAS guards — `neq` alone drops NULL rows (NULL <> x is
        # unknown), so e.g. an idempotency claim must spell out `col.is.null`.
        self._or_filters.append(conditions)
        return self

    def _apply_or_filters(self, params: dict) -> None:
        _apply_or_groups(params, self._or_filters)

    def neq(self, column: str, value: str) -> "UpdateBuilder":
        self._filters.append((column, "neq", value))
        return self

    def is_(self, column: str, value: str) -> "UpdateBuilder":
        self._filters.append((column, "is", value))
        return self

    def in_(self, column: str, values: list[str]) -> "UpdateBuilder":
        values_str = ",".join(f'"{v}"' for v in values)
        self._filters.append((column, "in", f"({values_str})"))
        return self

    def lt(self, column: str, value: str) -> "UpdateBuilder":
        self._filters.append((column, "lt", value))
        return self

    def lte(self, column: str, value: str) -> "UpdateBuilder":
        self._filters.append((column, "lte", value))
        return self

    def gt(self, column: str, value: str) -> "UpdateBuilder":
        self._filters.append((column, "gt", value))
        return self

    def gte(self, column: str, value: str) -> "UpdateBuilder":
        self._filters.append((column, "gte", value))
        return self

    def execute(self) -> "TableResponse":
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        params = {}
        _apply_filters_to_params(params, self._filters)
        self._apply_or_filters(params)

        headers = {
            **self.client.headers,
            "Prefer": "return=representation",
        }

        client = get_sync_http_client()
        response = client.patch(url, json=self.data, params=params, headers=headers)
        if response.status_code in (200, 201, 204):
            if response.content:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    return TableResponse(data[0])
                return TableResponse(data)
            return TableResponse(None)
        raise _build_postgrest_error(response, "Update failed")

    async def execute_async(self) -> "TableResponse":
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        params = {}
        _apply_filters_to_params(params, self._filters)
        self._apply_or_filters(params)

        headers = {
            **self.client.headers,
            "Prefer": "return=representation",
        }

        client = get_async_http_client()
        start = time.monotonic()
        response = await client.patch(url, json=self.data, params=params, headers=headers)
        duration_ms = int((time.monotonic() - start) * 1000)
        log_extra = {
            "event": "db_query",
            "table": self.table_name,
            "operation": "update",
            "status": response.status_code,
            "duration_ms": duration_ms,
        }
        if response.status_code in (200, 201, 204):
            if duration_ms > 200:
                logger.info("db_query", extra=log_extra)
            else:
                logger.debug("db_query", extra=log_extra)
            if response.content:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    return TableResponse(data[0])
                return TableResponse(data)
            return TableResponse(None)
        logger.warning("db_query", extra=log_extra)
        raise _build_postgrest_error(response, "Update failed")


class DeleteBuilder:
    def __init__(self, client: SupabaseAdminClient, table_name: str, filters: list):
        self.client = client
        self.table_name = table_name
        self._filters = filters

    def eq(self, column: str, value: str) -> "DeleteBuilder":
        self._filters.append((column, "eq", value))
        return self

    async def execute_async(self) -> "TableResponse":
        url = f"{self.client.url}/rest/v1/{self.table_name}"
        params = {}
        _apply_filters_to_params(params, self._filters)

        headers = {
            **self.client.headers,
            "Prefer": "return=representation",
        }

        client = get_async_http_client()
        start = time.monotonic()
        response = await client.delete(url, params=params, headers=headers)
        duration_ms = int((time.monotonic() - start) * 1000)
        log_extra = {
            "event": "db_query",
            "table": self.table_name,
            "operation": "delete",
            "status": response.status_code,
            "duration_ms": duration_ms,
        }
        if response.status_code in (200, 204):
            if duration_ms > 200:
                logger.info("db_query", extra=log_extra)
            else:
                logger.debug("db_query", extra=log_extra)
            if response.content:
                data = response.json()
                return TableResponse(data if isinstance(data, list) else [data])
            return TableResponse([])
        logger.warning("db_query", extra=log_extra)
        raise _build_postgrest_error(response, "Delete failed")


class TableResponse:
    def __init__(self, data):
        self.data = data


def insert_many(client: SupabaseAdminClient, table_name: str, data: list[dict]) -> InsertManyBuilder:
    return InsertManyBuilder(client, table_name, data)


@lru_cache()
def get_supabase_admin_client() -> SupabaseAdminClient:
    settings = get_settings()
    return SupabaseAdminClient(
        settings.SUPABASE_URL,
        settings.SUPABASE_SECRET_KEY
    )
