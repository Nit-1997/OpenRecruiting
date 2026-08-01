import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.service.concept_extractor import ConceptExtractor


@pytest.fixture
def extractor():
    return ConceptExtractor(api_key="test-key", model="gpt-4o-mini")


@pytest.mark.asyncio
async def test_extract_returns_parsed_json(extractor):
    expected = {"companies": [{"name": "Calendly"}], "markets": [{"name": "B2B SaaS"}]}
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(expected)
    with patch.object(extractor._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_response):
        result = await extractor.extract("some text", "extract companies")
    assert result["companies"][0]["name"] == "Calendly"


@pytest.mark.asyncio
async def test_extract_returns_empty_on_invalid_json(extractor):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "not valid json"
    with patch.object(extractor._client.chat.completions, "create", new_callable=AsyncMock, return_value=mock_response):
        result = await extractor.extract("text", "prompt")
    assert result == {}


@pytest.mark.asyncio
async def test_extract_raises_on_api_error(extractor):
    with patch.object(extractor._client.chat.completions, "create", new_callable=AsyncMock, side_effect=Exception("API error")):
        with pytest.raises(Exception, match="API error"):
            await extractor.extract("text", "prompt")
