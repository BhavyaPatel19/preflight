"""Local models via Ollama (``ollama serve``). Default: qwen3:14b, thinking off."""

from __future__ import annotations

import json
from typing import Any

import httpx

from preflight.llm import LLMUnavailable


class OllamaLLM:
    def __init__(self, model: str = "qwen3:14b", url: str = "http://localhost:11434",
                 *, client: httpx.Client | None = None, timeout: float = 300.0):
        self.name = f"ollama/{model}"
        self.model = model
        self.url = url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    def available(self) -> bool:
        try:
            r = self._client.get(f"{self.url}/api/tags", timeout=2.0)
            return r.status_code == 200 and any(
                m.get("name") == self.model or m.get("name", "").startswith(self.model)
                for m in r.json().get("models", [])
            )
        except httpx.HTTPError:
            return False

    def complete_json(self, system: str, user: str, schema: dict[str, Any],
                      *, max_tokens: int = 400) -> dict[str, Any]:
        try:
            r = self._client.post(f"{self.url}/api/chat", json={
                "model": self.model, "stream": False, "think": False, "format": schema,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "options": {"temperature": 0.2, "num_predict": max_tokens},
            })
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"ollama at {self.url}: {e}") from e
        content = r.json().get("message", {}).get("content", "")
        try:
            out = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"model returned non-JSON despite schema: {content[:120]!r}") from e
        if not isinstance(out, dict):
            raise ValueError("model returned a non-object")
        return out
