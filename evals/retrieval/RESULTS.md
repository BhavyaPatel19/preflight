# Retrieval evaluation

Run `f0bb228` at 2026-11-10T12:27:13+00:00 · corpus 75,709 documents / 316,226 chunks · embedder `models/bge-large-asrs` · reranker `BAAI/bge-reranker-base` · 40 candidates per channel, RRF k=60

**Synopsis → narrative** (300 ASRS queries; synopsis chunks hidden):

| config | Recall@5 | Recall@10 | Recall@20 | MRR@20 | nDCG@10 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 0.607 | 0.690 | 0.750 | 0.500 | 0.542 | 54 | 219 |
| lexical | 0.363 | 0.407 | 0.483 | 0.264 | 0.295 | 209 | 237 |
| hybrid | 0.570 | 0.657 | 0.733 | 0.456 | 0.499 | 242 | 274 |
| dense+rerank | 0.557 | 0.643 | 0.733 | 0.418 | 0.467 | 736 | 821 |
| hybrid+rerank | 0.517 | 0.613 | 0.707 | 0.406 | 0.450 | 961 | 1197 |

**Rerank lift** (nDCG@10, hybrid+rerank − dense): **-0.092**

**Identifier queries** (50 `runway <NN>` queries with the airport as a metadata filter; relevant = chunk at that airport mentioning that runway):

| config | P@10 |
|---|---:|
| dense | 0.620 |
| lexical | 0.746 |
| hybrid | 0.746 |
| dense+rerank | 0.752 |
| hybrid+rerank | 0.776 |

**Where hybrid+rerank misses** (65 of 300 synopsis queries, 21.7%, have no relevant report anywhere in the 40-candidate pool):

| synopsis length | queries | Recall@20 | not in pool |
|---|---:|---:|---:|
| ≤12 words | 13 | 0.462 | 0.462 |
| 13–25 words | 136 | 0.581 | 0.309 |
| >25 words | 151 | 0.841 | 0.113 |

| target narrative | queries | Recall@20 | not in pool |
|---|---:|---:|---:|
| 1 chunk | 129 | 0.690 | 0.209 |
| 2–3 chunks | 130 | 0.738 | 0.215 |
| 4+ chunks | 41 | 0.659 | 0.244 |

Verbatim misses (synopsis → how the target narrative opens):

- *C172 instructor pilot reported engine malfunctioning and having to make a 180 turn back to the airport to land safely.* → “This flight was a cross country instructional flight with my student. We left for ZZZ expecting to return to ZZZ1 back to the flight school. At ZZZ1 we did the normal checklist procedures. In the run up prior to takeoff from ZZZ1 I verified…”
- *SA-227AC Captain reported flight crew Hazmat document verification form of DG cargo not completed at departure airport. FAA Ramp Checker on arrival noted the flight crew error.* → “Upon arrival of the third package cart; the driver hands me both the load manifest and the Hazmat which was a Class 3. I inspected the box and retrieved one copy of the shipping papers and left another copy with the box. I then took a photo…”
- *Air carrier Captain reported deviating from final approach due to proximity of aircraft approaching parallel runway at SFO airport.* → “We had been monitoring the wind event and ATIS wind changes enroute from ZZZ to SFO. Wind changed from a headwind for Runway 28 to 020 [at] 10 kts. Crossing ZZZZZ at 11;000 feet we were assigned the visual to 28R. On a vector we were reassi…”
- *A B737-700 Captain reported landing with a 22 knot tailwind component in rapidly changing weather conditions.* → “Arrival ATIS for ONT indicated light winds; ref +5. A new ATIS came out indicating an increase and a direction change; more northerly of ref +12. On the first approach; we were held high because of GA traffic. When finally cleared for the v…”
- *B767 flight crew reported ground crew was active around the aircraft and had opened a cargo door before they set the brakes at the gate. Parking brake failed to set on the first try and the aircraft r* → “Arrived at MIA and followed DGS to stop. Before I could set the brakes and shut down engines; fwd cargo door was opened. Noise and lights distracted me as I noticed the immediate danger of a cargo door open in front of a running engine. We …”

What this measures: paraphrase-to-passage retrieval and exact-identifier retrieval,
both with objective labels. What it does not: judged precedent relevance for
briefing-style queries — that is the Sprint 5 golden set.
