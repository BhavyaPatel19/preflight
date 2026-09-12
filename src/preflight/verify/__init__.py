"""Grounding verification: is each claim entailed by the passage it cites?"""

from preflight.verify.ground import premise_for, with_verification
from preflight.verify.nli import HFVerifier, Verifier

__all__ = ["HFVerifier", "Verifier", "premise_for", "with_verification"]
