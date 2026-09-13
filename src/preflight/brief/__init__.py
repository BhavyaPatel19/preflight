"""Briefing assembly.

The core is deterministic: records in, cited findings and explicit abstentions
out, no model in the loop. Precedent adds prior reports from the corpus. The
LLM layer (narrate) rewrites precedent queries and writes prose — every
sentence verified against the citations and dropped if unsupported.
"""

from preflight.brief.core import build_briefing
from preflight.brief.narrate import with_narrative
from preflight.brief.precedent import load_retriever, with_precedent
from preflight.brief.render import render_text

__all__ = ["build_briefing", "load_retriever", "render_text", "with_narrative", "with_precedent"]
