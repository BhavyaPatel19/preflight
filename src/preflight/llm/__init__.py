"""Language models behind one small protocol.

The briefing's deterministic core needs no model. The LLM layer adds two
things — precedent-query rewriting and narrative prose — and every sentence it
writes is checked by the grounding verifier and dropped if unsupported. So the
model is swappable and its quality is *measured* (unsupported-claim rate), not
assumed: a local open-weight model is the default at zero cost; the Anthropic
implementation is present, tested against a fake client, and dormant until a
key exists — then the same eval runs against it for the comparison row.

Both backends take the same JSON schema: Ollama's ``format`` and Anthropic's
``output_config.format`` are the same dict.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol, runtime_checkable

from preflight.config import settings


class LLMUnavailable(RuntimeError):
    """The configured provider cannot serve (not running, no key)."""


@runtime_checkable
class LLM(Protocol):
    name: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any],
                      *, max_tokens: int = 400) -> dict[str, Any]:
        """One schema-constrained completion. Raises LLMUnavailable if the backend is down."""
        ...


def load_llm() -> LLM | None:
    """The configured provider, or None when ``PREFLIGHT_LLM=none`` or it is unreachable."""
    s = settings()
    if s.llm_provider == "none":
        return None
    if s.llm_provider == "ollama":
        from preflight.llm.ollama import OllamaLLM

        llm = OllamaLLM(s.ollama_model, s.ollama_url)
        return llm if llm.available() else None
    if s.llm_provider == "anthropic":
        from preflight.llm.anthropic import AnthropicLLM

        return AnthropicLLM(s.anthropic_model) if s.anthropic_api_key else None
    return None


def fan_out[T, R](fn: Callable[[T], R], items: Sequence[T], *,
                  workers: int | None = None) -> list[R]:
    """``[fn(x) for x in items]`` with up to ``workers`` calls in flight; results in order.

    Per-finding model calls are independent, and a batching server (Ollama with
    ``OLLAMA_NUM_PARALLEL``, or a hosted API) serves them concurrently for close to
    the cost of one. ``fn`` must handle its own errors: an exception in any call
    propagates after the others finish.
    """
    workers = min(workers or settings().llm_concurrency, len(items))
    if workers <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="llm") as ex:
        return list(ex.map(fn, items))


__all__ = ["LLM", "LLMUnavailable", "fan_out", "load_llm"]
