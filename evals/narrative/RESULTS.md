# Narrative evaluation

Run `d64c922` at 2026-09-13T07:55:45+00:00 · model `ollama/qwen3:14b` · verifier `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` at 0.5 · 36 findings, 7.6 s per finding

| metric | value |
|---|---:|
| sentences generated | 99 |
| kept (verifier supports them) | 98 |
| dropped | 1 |
| **unsupported-claim rate** | **0.01** |
| failed model calls | 0 |

| finding kind | findings | generated | kept | unsupported rate |
|---|---:|---:|---:|---:|
| approach aids | 2 | 3 | 3 | 0.0 |
| delay | 20 | 60 | 59 | 0.017 |
| lighting | 4 | 9 | 9 | 0.0 |
| navaid | 1 | 3 | 3 | 0.0 |
| runway | 6 | 17 | 17 | 0.0 |
| taxiway | 3 | 7 | 7 | 0.0 |

Kept (sample):

- (0.99) Runway 25L at KLAX is closed due to work in progress until 15 Sep 1400Z.
- (1.00) The closure of Runway 25L at KLAX is in effect from 15 Sep 0600Z to 15 Sep 1400Z.
- (0.99) Runway 25L at KLAX remains closed until 15 Sep 1400Z as part of ongoing work.
- (0.98) ILS 04R at KEWR is unserviceable due to maintenance until 16 Sep 0000Z (estimated).
- (0.98) The ILS for runway 04R at KEWR is out of service until 16 Sep 0000Z (estimated).

Dropped — read these to judge whether the verifier was right:

- (0.03, delay) For 53 Sunday 05:00 hours between June 2025 and May 2026, 80% of arrivals had delays between -17 and 17 minutes.

What this measures: the share of a model's sentences the verifier cannot tie to the
cited sources, on the briefing's own findings. A dropped sentence is not necessarily
false — it may be interpretation the sources do not state — and in a safety-adjacent
output that is the right thing to drop. Run per provider for the comparison row.
