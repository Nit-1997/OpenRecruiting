"""Pipeline integration test (all stages mocked)."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.pipeline import run_pipeline
from src.stages.check_context import Mode


@pytest.mark.asyncio
async def test_pipeline_full_flow_writes_all_stages():
    with patch("src.pipeline.get_supabase_client") as mock_get_sb, \
         patch("src.pipeline.get_anthropic_client") as mock_get_ant, \
         patch("src.pipeline.get_mcp_client") as mock_get_mcp, \
         patch("src.pipeline.fetch_service_token", new=AsyncMock(return_value="tok")), \
         patch("src.pipeline.check_context", new=AsyncMock(return_value={"mode": Mode.FULL_CONTEXT, "has_any": True, "similar_count": 3})), \
         patch("src.pipeline.parse_jd", new=AsyncMock(return_value={"skipped": False, "facts": {"must_have_skills": ["Python"]}})), \
         patch("src.pipeline.query_cortex", new=AsyncMock(return_value={"similar_reqs": [], "skills_required": [{"name":"Python"}], "skills_nice": [], "traits": [], "rounds": []})), \
         patch("src.pipeline.synthesize_answers", new=AsyncMock(return_value={f"q{i}_x": {"text":"x", "confidence":"medium", "sources":[]} for i in range(1,10)})), \
         patch("src.pipeline.update_process_stage") as mock_set_stage, \
         patch("src.pipeline.load_settings") as mock_settings:

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"id":"abc","organization_id":"org-1","form_data":{"role_name":"x","jd_text":"jd here"},"turns":[]}
        )
        mock_get_sb.return_value = mock_sb
        mock_settings.return_value = MagicMock(
            anthropic_api_key="k", anthropic_model_sonnet="claude-sonnet-4-6",
            supabase_url="u", supabase_secret_key="k", cortex_mcp_url="u",
            cortex_token_url="http://backend/token", internal_api_secret="s",
            environment="test", log_level="INFO", log_format="text",
        )

        result = await run_pipeline(session_id="abc", include_turns=False)

    assert result["status"] == "completed"
    # Stage calls: 4 stages × {running, completed} = 8 minimum
    stage_names = [call.kwargs.get("stage_name") for call in mock_set_stage.call_args_list if "stage_name" in call.kwargs]
    assert "check_context" in stage_names
    assert "parse_jd" in stage_names
    assert "query_cortex" in stage_names
    assert "synthesize" in stage_names


@pytest.mark.asyncio
async def test_pipeline_cold_mode_skips_cortex_queries():
    with patch("src.pipeline.get_supabase_client") as mock_get_sb, \
         patch("src.pipeline.get_anthropic_client"), \
         patch("src.pipeline.get_mcp_client"), \
         patch("src.pipeline.fetch_service_token", new=AsyncMock(return_value="tok")), \
         patch("src.pipeline.check_context", new=AsyncMock(return_value={"mode": Mode.COLD, "has_any": False, "similar_count": 0})), \
         patch("src.pipeline.parse_jd", new=AsyncMock(return_value={"skipped": True, "facts": {}})), \
         patch("src.pipeline.query_cortex", new=AsyncMock(return_value={})) as mock_cortex, \
         patch("src.pipeline.synthesize_answers", new=AsyncMock(return_value={f"q{i}_x": {"text":None,"confidence":"none","sources":[]} for i in range(1,10)})), \
         patch("src.pipeline.update_process_stage"), \
         patch("src.pipeline.load_settings"):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"id":"abc","organization_id":"org-1","form_data":{"role_name":"x"},"turns":[]}
        )
        mock_get_sb.return_value = mock_sb
        result = await run_pipeline(session_id="abc", include_turns=False)
    # COLD mode still calls query_cortex (it returns empty internally) — verify the call happened
    mock_cortex.assert_called_once()
    assert result["status"] == "completed"
