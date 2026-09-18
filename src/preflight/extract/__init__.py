"""The NOTAM entity extractor: synthetic training data, gold set, model, eval.

Real NOTAM feeds are out of scope by choice (ADR 0002), so the token classifier
that Sprint 2 planned is trained on NOTAMs *generated* from the same Q-code
taxonomy and contraction vocabulary the rule decoder uses, and evaluated on the
real-format samples this repository already holds — hand-labelled. Every number
it produces says which of those two it was measured on.
"""
