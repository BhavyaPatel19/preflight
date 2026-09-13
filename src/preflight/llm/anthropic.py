"""Claude via the Anthropic SDK. Dormant until ANTHROPIC_API_KEY exists.

Default model is Claude Opus 5 — this path is for the comparison rows, where
the question is "how much better is the best model", so it uses the best one.
Structured output via ``output_config.format`` with the same JSON schema the
local backend takes.
"""

from __future__ import annotations

import json
from typing import Any

from preflight.llm import LLMUnavailable


class AnthropicLLM:
    def __init__(self, model: str = "claude-opus-5", *, client: Any = None):
        self.name = f"anthropic/{model}"
        self.model = model
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise LLMUnavailable("anthropic SDK not installed: uv sync --extra llm") from e
            self._client = anthropic.Anthropic()
        return self._client

    def complete_json(self, system: str, user: str, schema: dict[str, Any],
                      *, max_tokens: int = 400) -> dict[str, Any]:
        client = self._get_client()
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=max(max_tokens, 1024),
                system=system,
                messages=[{"role": "user", "content": user}],
                thinking={"type": "adaptive"},
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except Exception as e:  # noqa: BLE001 — typed SDK errors are re-raised uniformly
            name = type(e).__name__
            if name in {"AuthenticationError", "PermissionDeniedError", "APIConnectionError"}:
                raise LLMUnavailable(f"anthropic: {name}: {e}") from e
            raise
        if getattr(response, "stop_reason", None) == "refusal":
            raise ValueError("model refused the request")
        text = next(b.text for b in response.content if getattr(b, "type", "") == "text")
        out = json.loads(text)
        if not isinstance(out, dict):
            raise ValueError("model returned a non-object")
        return out
