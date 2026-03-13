import json
from typing import Iterable, Optional

from openai import OpenAI

from src.config import OPENAI_MODEL, load_openai_key
from src.errors import AgentExecutionError


class OpenAIService:
    def __init__(self, api_key=None, model=None, client=None):
        self._api_key = api_key if api_key is not None else load_openai_key(required=False)
        self.model = model or OPENAI_MODEL
        self._client = client if client is not None else None
        if self._client is None and self._api_key:
            self._client = OpenAI(api_key=self._api_key)

    def is_available(self):
        return self._client is not None

    def run_json_prompt(
        self,
        system_prompt,
        user_prompt,
        expected_keys: Optional[Iterable[str]] = None,
        temperature=0.2,
        max_completion_tokens=1200,
    ):
        if not self.is_available():
            raise AgentExecutionError(
                "OpenAI is not configured for AI-assisted orchestration."
            )

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            raise AgentExecutionError(
                "The AI workflow request failed.",
                details=str(exc),
            ) from exc

        content = self._extract_message_content(response)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AgentExecutionError(
                "The AI workflow returned an invalid JSON response.",
                details=content,
            ) from exc

        missing_keys = [
            key for key in list(expected_keys or []) if key not in payload
        ]
        if missing_keys:
            raise AgentExecutionError(
                "The AI workflow response was missing required fields.",
                details=", ".join(missing_keys),
            )
        return payload

    @staticmethod
    def _extract_message_content(response):
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise AgentExecutionError("The AI workflow returned no choices.")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message else None
        if not content:
            raise AgentExecutionError("The AI workflow returned an empty message.")
        return content
