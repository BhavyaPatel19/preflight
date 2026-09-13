# Grounding evaluation

Run `d64c922` at 2026-09-13T07:55:05+00:00 · verifier `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` · 36 true claims, each paired with one materially corrupted copy (citation unchanged).

| threshold | true-claim acceptance ↑ | corruption rejection ↑ |
|---|---:|---:|
| 0.3 | 1.000 | 0.944 |
| 0.5 | 1.000 | 0.972 |
| 0.7 | 1.000 | 0.972 |

Per claim kind at the production threshold (0.5):

| kind | n | true-claim acceptance | corruption rejection |
|---|---:|---:|---:|
| delay | 20 | 1.000 | 0.950 |
| notam | 16 | 1.000 | 1.000 |

Misses at 0.5 (true claim scored < 0.5, or corrupted claim ≥ 0.5):

| kind | corruption | true | corrupt | claim |
|---|---|---:|---:|---|
| delay | median -10→35 min | 0.99 | 0.90 | Over 52 Sun 06:00 hours in the BTS record (Jun 2025–May 2026), median arrival de |

What this measures: whether the NLI verifier can tell a claim the citation supports
from one it does not, on the briefing's own phrasing. What it does not: LLM-written
prose — that arrives with the agent layer, and this harness is what will gate it.
