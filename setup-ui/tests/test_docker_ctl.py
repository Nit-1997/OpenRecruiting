import httpx
import pytest

from app.docker_ctl import Container, DockerControl, DockerError


def _payload(service: str, state: str = "running", status: str = "Up 2 minutes (healthy)"):
    return {
        "Id": f"id-{service}",
        "State": state,
        "Status": status,
        "Labels": {
            "com.docker.compose.project": "openrecruiting",
            "com.docker.compose.service": service,
        },
    }


def _client(handler) -> DockerControl:
    ctl = DockerControl("http://proxy:2375")
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    class Patched(original):  # type: ignore[misc,valid-type]
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    httpx.AsyncClient = Patched  # type: ignore[misc]
    ctl._restore = lambda: setattr(httpx, "AsyncClient", original)  # type: ignore[attr-defined]
    return ctl


@pytest.mark.asyncio
async def test_only_this_projects_containers_are_listed():
    """A developer's unrelated containers must never appear, and must never be
    restart targets."""
    other = _payload("postgres")
    other["Labels"]["com.docker.compose.project"] = "someone-elses-stack"

    ctl = _client(lambda r: httpx.Response(200, json=[_payload("backend"), other]))
    try:
        names = [c.name for c in await ctl.list_containers()]
    finally:
        ctl._restore()

    assert names == ["backend"]


@pytest.mark.asyncio
async def test_health_is_parsed_from_the_status_string():
    ctl = _client(
        lambda r: httpx.Response(
            200,
            json=[
                _payload("a", status="Up 1 minute (healthy)"),
                _payload("b", status="Up 1 minute (unhealthy)"),
                _payload("c", status="Up 1 second (health: starting)"),
                _payload("d", status="Up 5 minutes"),
            ],
        )
    )
    try:
        by_name = {c.name: c for c in await ctl.list_containers()}
    finally:
        ctl._restore()

    assert by_name["a"].health == "healthy"
    assert by_name["b"].health == "unhealthy"
    assert by_name["c"].health == "starting"
    assert by_name["d"].health is None


def test_a_running_container_without_a_healthcheck_counts_as_ok():
    """Most services in this stack define no healthcheck. Treating "no health
    reported" as failure would show half the grid red on a working system."""
    assert Container("landing", "running", None).ok is True
    assert Container("landing", "running", "healthy").ok is True
    assert Container("landing", "running", "unhealthy").ok is False
    assert Container("landing", "exited", None).ok is False


@pytest.mark.asyncio
async def test_restart_posts_to_the_containers_restart_endpoint():
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/containers/json"):
            return httpx.Response(200, json=[_payload("voice-agent")])
        return httpx.Response(204)

    ctl = _client(handler)
    try:
        await ctl.restart("voice-agent")
    finally:
        ctl._restore()

    assert ("POST", "/v1.47/containers/id-voice-agent/restart") in seen


@pytest.mark.asyncio
async def test_restarting_an_unknown_service_is_refused_before_any_post():
    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(request.url.path)
        return httpx.Response(200, json=[_payload("backend")])

    ctl = _client(handler)
    try:
        with pytest.raises(DockerError, match="No container found"):
            await ctl.restart("not-a-service")
    finally:
        ctl._restore()

    assert posts == []


@pytest.mark.asyncio
async def test_a_proxy_error_surfaces_as_a_readable_message():
    ctl = _client(lambda r: httpx.Response(403))
    try:
        with pytest.raises(DockerError, match="Could not reach the Docker proxy"):
            await ctl.list_containers()
    finally:
        ctl._restore()


@pytest.mark.asyncio
async def test_wait_until_ok_returns_false_rather_than_hanging():
    """A service that never comes back must be reported next to that service,
    not raised as an exception that hides which of five restarts failed."""
    ctl = _client(lambda r: httpx.Response(200, json=[_payload("backend", "exited", "Exited (1)")]))
    try:
        result = await ctl.wait_until_ok("backend", timeout=0.1)
    finally:
        ctl._restore()

    assert result is False
