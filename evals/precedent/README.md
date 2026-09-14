# Labeling the precedent sheet

`labels.csv` has 100 (hazard, prior report) pairs. For each row, read the hazard and the prior
report and decide: **is the report relevant precedent for a crew facing this hazard?** Put `y`
or `n` in the `relevant_precedent (y/n)` column. Notes are optional.

Relevant means: the report describes an operational situation, error or outcome a crew facing
this hazard could plausibly encounter — same kind of hazard and phase of flight, or a consequence
that follows from it. The airport does not need to match. Same general topic but a different kind
of hazard is **not** relevant.

The model judge's verdicts are deliberately not on the sheet. When you're done:

```bash
preflight eval precedent --score
```

reports Cohen's κ between the judge and you, and the precision of what the briefing actually
attaches, measured against your labels. Until then, every precedent number is judge-estimated
and the results file says so.

It's about 30 minutes. Skimming is fine — the judge sees exactly what you see.
