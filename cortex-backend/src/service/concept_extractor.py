import json
import structlog
from openai import AsyncOpenAI

logger = structlog.get_logger(__name__)


class ConceptExtractor:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def extract(self, text: str, system_prompt: str) -> dict:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("concept_extraction_invalid_json", model=self._model)
            return {}
