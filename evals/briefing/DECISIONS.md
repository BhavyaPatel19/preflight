
**Decision (2026-11-11): TEMPO forecast groups alarm.** With TAFs in the briefing, recall rose
0.19 → 0.27 and false alarms 0.10 → 0.16, and 8 of the 12 TAF-only findings that fired on
matched negatives came from TEMPO groups. Briefing TEMPO conditions as information only would cut
some of those false alarms and some of the catches. The owner chose to keep TEMPO at full
severity: a crew is better served by an alarm on conditions forecast to occur temporarily than
by a note they may skim. PROB30/40 groups stay one severity step lower (`brief/core.py`,
`_period_severity`). Revisit when the matched-negative set is large enough to price the trade.
