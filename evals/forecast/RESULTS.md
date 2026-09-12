# Delay-forecast evaluation

Run `12718af` at 2026-09-12T13:07:23-07:00 · BTS hourly arrival delay 2025-06-01 → 2026-05-31 (1,080,277 airport-hours) · rolling-origin backtest, 14 daily origins × 29 airports = 406 forecasts of 24 h

| forecaster | MASE ↓ | mean pinball (q10/50/90) ↓ |
|---|---:|---:|
| seasonal-naive (last week, same hour) | 1.067 | — |
| climatology (weekday-hour quantiles) | 0.751 | 5.294 |
| `amazon/chronos-bolt-small` zero-shot | 0.715 | 5.124 |

MASE < 1 beats repeating last week; the README target is < 0.85.

| airport | seasonal-naive | climatology | chronos-bolt |
|---|---:|---:|---:|
| KATL | 1.311 | 0.988 | 0.873 |
| KBOS | 0.905 | 0.577 | 0.550 |
| KBWI | 0.989 | 0.776 | 0.703 |
| KCLT | 1.049 | 0.752 | 0.717 |
| KDCA | 1.099 | 0.971 | 1.028 |
| KDEN | 1.150 | 0.731 | 0.698 |
| KDFW | 1.478 | 1.018 | 0.960 |
| KDTW | 1.244 | 0.758 | 0.725 |
| KEWR | 1.685 | 1.046 | 1.014 |
| KFLL | 0.870 | 0.686 | 0.683 |
| KIAD | 1.108 | 0.804 | 0.838 |
| KIAH | 1.157 | 0.748 | 0.725 |
| KJFK | 1.332 | 0.881 | 0.879 |
| KLAS | 0.877 | 0.526 | 0.481 |
| KLAX | 1.175 | 0.734 | 0.714 |
| KLGA | 1.160 | 0.765 | 0.732 |
| KMCO | 0.928 | 0.642 | 0.623 |
| KMDW | 0.993 | 0.789 | 0.743 |
| KMIA | 0.860 | 0.545 | 0.555 |
| KMSP | 1.040 | 0.699 | 0.671 |
| KORD | 0.725 | 0.429 | 0.416 |
| KPDX | 0.884 | 0.601 | 0.575 |
| KPHL | 1.132 | 0.778 | 0.773 |
| KPHX | 0.899 | 0.599 | 0.586 |
| KSAN | 0.860 | 0.601 | 0.601 |
| KSEA | 1.069 | 0.766 | 0.665 |
| KSFO | 0.961 | 1.071 | 0.793 |
| KSLC | 0.914 | 0.673 | 0.646 |
| KTPA | 1.094 | 0.812 | 0.759 |

The briefing cites climatology, not the model: BTS lands with a ~3-month lag, and a
flight next week is beyond any honest horizon. The model earns its place, or does not,
on this table.
