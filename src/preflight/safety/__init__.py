"""Untrusted-input handling. NOTAM and report text is data, never instructions."""

from preflight.safety.injection import InjectionVerdict, detect

__all__ = ["InjectionVerdict", "detect"]
