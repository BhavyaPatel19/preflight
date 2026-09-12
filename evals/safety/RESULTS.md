# Injection red-team evaluation

Run `64cab66` at 2026-09-12T20:31:20+00:00 · 60 adversarial NOTAMs in six families · 19 benign NOTAMs as controls.

| metric | value |
|---|---:|
| detector recall on adversarial NOTAMs | 1.000 |
| false-positive rate on benign NOTAMs | 0.000 |
| adversarial NOTAMs that still parse to data | 60 / 60 |
| … of which flagged low-confidence by the decoder | 3 |

| family | n | recall |
|---|---:|---:|
| exfil | 10 | 1.000 |
| format | 10 | 1.000 |
| obfuscated | 10 | 1.000 |
| override | 10 | 1.000 |
| role | 10 | 1.000 |
| steer | 10 | 1.000 |

What this measures: whether injected instructions in NOTAM text are detected before any
model sees them, and that the deterministic pipeline treats them as data regardless. The
detector's rules were iterated against this same set, so treat the recall as an upper
bound until a held-out set exists. What it does not yet: LLM resistance — the README's
100% target is scored against this set once the agent layer exists.
