"""Tests for the generic Lambda invoke helper."""

from unittest.mock import MagicMock, patch
import pytest

import app.services.lambda_invoke as lambda_invoke
from app.services.lambda_invoke import invoke_lambda_async


@pytest.fixture(autouse=True)
def _reset_module_client():
    """The boto3 lambda client is cached at module scope (BE-A1); reset it
    between tests so a MagicMock from one test doesn't leak into another."""
    lambda_invoke._lambda_client = None
    yield
    lambda_invoke._lambda_client = None


@pytest.mark.asyncio
async def test_invoke_lambda_calls_boto3_with_event_type():
    with patch("app.services.lambda_invoke.boto3") as mock_boto:
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.invoke.return_value = {"StatusCode": 202}
        await invoke_lambda_async(
            function_arn="arn:aws:lambda:us-west-1:111:function:test",
            payload={"session_id": "abc"},
        )
        mock_boto.client.assert_called_once_with("lambda", region_name="us-west-1")
        mock_client.invoke.assert_called_once()
        call_kwargs = mock_client.invoke.call_args.kwargs
        assert call_kwargs["FunctionName"] == "arn:aws:lambda:us-west-1:111:function:test"
        assert call_kwargs["InvocationType"] == "Event"
        import json
        assert json.loads(call_kwargs["Payload"]) == {"session_id": "abc"}


@pytest.mark.asyncio
async def test_invoke_lambda_caches_client_across_calls():
    """boto3 lambda client is built once (module scope) and reused — building a
    new client per call is wasteful and was the BE-A1 offender."""
    with patch("app.services.lambda_invoke.boto3") as mock_boto:
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.invoke.return_value = {"StatusCode": 202}
        await invoke_lambda_async("arn:test", {"x": 1})
        await invoke_lambda_async("arn:test", {"x": 2})
        mock_boto.client.assert_called_once()
        assert mock_client.invoke.call_count == 2


@pytest.mark.asyncio
async def test_invoke_lambda_raises_on_boto_error():
    with patch("app.services.lambda_invoke.boto3") as mock_boto:
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.invoke.side_effect = Exception("AWS error")
        with pytest.raises(Exception):
            await invoke_lambda_async("arn:test", {"x": 1})


@pytest.mark.asyncio
async def test_invoke_lambda_offloads_to_thread():
    """The blocking boto3 invoke must run via asyncio.to_thread, not inline on
    the event loop (BE-A2 offload completion)."""
    with patch("app.services.lambda_invoke.boto3") as mock_boto, \
         patch("app.services.lambda_invoke.asyncio.to_thread") as mock_to_thread:
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.invoke.return_value = {"StatusCode": 202}

        async def _passthrough(fn, *args):
            return fn(*args)

        mock_to_thread.side_effect = _passthrough
        await invoke_lambda_async("arn:test", {"x": 1})
        mock_to_thread.assert_called_once()
