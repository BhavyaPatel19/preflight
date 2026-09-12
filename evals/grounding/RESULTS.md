# Grounding evaluation

Run `6db0301` at 2026-09-12T20:22:55+00:00 · verifier `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` · 74 true claims, each paired with one materially corrupted copy (citation unchanged).

| threshold | true-claim acceptance ↑ | corruption rejection ↑ |
|---|---:|---:|
| 0.3 | 1.000 | 0.959 |
| 0.5 | 1.000 | 1.000 |
| 0.7 | 0.608 | 1.000 |

Per claim kind at the production threshold (0.5):

| kind | n | true-claim acceptance | corruption rejection |
|---|---:|---:|---:|
| delay | 29 | 1.000 | 1.000 |
| notam | 16 | 1.000 | 1.000 |
| weather | 29 | 1.000 | 1.000 |

What this measures: whether the NLI verifier can tell a claim the citation supports
from one it does not, on the briefing's own phrasing. What it does not: LLM-written
prose — that arrives with the agent layer, and this harness is what will gate it.
