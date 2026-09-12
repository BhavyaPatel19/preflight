"""Briefing assembly.

The core is deterministic: records in, cited findings and explicit abstentions
out, no model in the loop. The agent layer (Sprint 4) enriches this — adds
precedent, forecasts, prose — but every claim it makes still has to be
traceable to a record, and everything here is the floor it cannot fall below.
"""

from preflight.brief.core import build_briefing
from preflight.brief.render import render_text

__all__ = ["build_briefing", "render_text"]
