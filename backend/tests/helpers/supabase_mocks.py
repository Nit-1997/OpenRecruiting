import httpx

SUPABASE_URL = "http://test-supabase.local"


def rest_url(table):
    return f"{SUPABASE_URL}/rest/v1/{table}"


def auth_url(path=""):
    return f"{SUPABASE_URL}/auth/v1{path}"


def mock_select(respx_mock, table, data, method="GET", status=200):
    route = respx_mock.route(method=method, url=rest_url(table))
    route.mock(return_value=httpx.Response(status, json=data if isinstance(data, list) else [data]))
    return route


def mock_select_single(respx_mock, table, data, status=200):
    route = respx_mock.get(rest_url(table))
    json_data = [data] if data else []
    route.mock(return_value=httpx.Response(status, json=json_data))
    return route


def mock_insert(respx_mock, table, data, status=201):
    route = respx_mock.post(rest_url(table))
    json_data = [data] if isinstance(data, dict) else data
    route.mock(return_value=httpx.Response(status, json=json_data))
    return route


def mock_update(respx_mock, table, data=None, status=200):
    route = respx_mock.patch(rest_url(table))
    json_data = [data] if data else []
    route.mock(return_value=httpx.Response(status, json=json_data))
    return route


def mock_delete(respx_mock, table, data=None, status=200):
    route = respx_mock.delete(rest_url(table))
    json_data = [data] if data else []
    route.mock(return_value=httpx.Response(status, json=json_data))
    return route


def rpc_url(function_name):
    return f"{SUPABASE_URL}/rest/v1/rpc/{function_name}"


def mock_rpc(respx_mock, function_name, data, status=200):
    route = respx_mock.post(rpc_url(function_name))
    route.mock(return_value=httpx.Response(status, json=data))
    return route


def mock_invite_user(respx_mock, user_data=None, status=200):
    route = respx_mock.post(auth_url("/invite"))
    route.mock(return_value=httpx.Response(status, json=user_data or {"id": "new-user-id"}))
    return route


def mock_ban_user(respx_mock, status=200):
    route = respx_mock.put(url__regex=rf"{SUPABASE_URL}/auth/v1/admin/users/.*")
    route.mock(return_value=httpx.Response(status, json={}))
    return route


def mock_delete_auth_user(respx_mock, status=200):
    route = respx_mock.delete(url__regex=rf"{SUPABASE_URL}/auth/v1/admin/users/.*")
    route.mock(return_value=httpx.Response(status))
    return route


def mock_get_auth_user(respx_mock, user_data=None, status=200):
    route = respx_mock.get(url__regex=rf"{SUPABASE_URL}/auth/v1/admin/users/.*")
    route.mock(return_value=httpx.Response(status, json=user_data or {}))
    return route
