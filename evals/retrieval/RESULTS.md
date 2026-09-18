# Retrieval evaluation

Run `ebcc6c2` at 2026-09-18T06:03:58+00:00 · corpus 75,709 documents / 316,226 chunks · embedder `BAAI/bge-large-en-v1.5` · reranker `BAAI/bge-reranker-base` · 40 candidates per channel, RRF k=60

**Synopsis → narrative** (300 ASRS queries; synopsis chunks hidden):

| config | Recall@5 | Recall@10 | Recall@20 | MRR@20 | nDCG@10 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 0.410 | 0.463 | 0.527 | 0.321 | 0.351 | 61 | 232 |
| lexical | 0.363 | 0.407 | 0.483 | 0.264 | 0.294 | 194 | 224 |
| hybrid | 0.447 | 0.507 | 0.560 | 0.360 | 0.392 | 245 | 275 |
| dense+rerank | 0.453 | 0.517 | 0.560 | 0.357 | 0.393 | 728 | 815 |
| hybrid+rerank | 0.457 | 0.530 | 0.597 | 0.374 | 0.407 | 947 | 1186 |

**Rerank lift** (nDCG@10, hybrid+rerank − dense): **+0.056**

**Identifier queries** (50 `runway <NN>` queries with the airport as a metadata filter; relevant = chunk at that airport mentioning that runway):

| config | P@10 |
|---|---:|
| dense | 0.624 |
| lexical | 0.748 |
| hybrid | 0.736 |
| dense+rerank | 0.746 |
| hybrid+rerank | 0.774 |

**Where hybrid+rerank misses** (110 of 300 synopsis queries, 36.7%, have no relevant report anywhere in the 40-candidate pool):

| synopsis length | queries | Recall@20 | not in pool |
|---|---:|---:|---:|
| ≤12 words | 13 | 0.385 | 0.538 |
| 13–25 words | 136 | 0.412 | 0.551 |
| >25 words | 151 | 0.781 | 0.185 |

| target narrative | queries | Recall@20 | not in pool |
|---|---:|---:|---:|
| 1 chunk | 129 | 0.605 | 0.349 |
| 2–3 chunks | 130 | 0.615 | 0.362 |
| 4+ chunks | 41 | 0.512 | 0.439 |

Verbatim misses (synopsis → how the target narrative opens):

- *PA 28R-201 instructor reported a complete throttle failure; and dead-sticking the aircraft to a safe landing.* → “My student and I went out for our flight. We had a bit of a delay due to high volume traffic and departed North West heading towards the practice area. Once over the alert area; we proceeded to do a few basic maneuvers: We did a few sets of…”
- *C172 instructor pilot reported engine malfunctioning and having to make a 180 turn back to the airport to land safely.* → “This flight was a cross country instructional flight with my student. We left for ZZZ expecting to return to ZZZ1 back to the flight school. At ZZZ1 we did the normal checklist procedures. In the run up prior to takeoff from ZZZ1 I verified…”
- *SA-227AC Captain reported flight crew Hazmat document verification form of DG cargo not completed at departure airport. FAA Ramp Checker on arrival noted the flight crew error.* → “Upon arrival of the third package cart; the driver hands me both the load manifest and the Hazmat which was a Class 3. I inspected the box and retrieved one copy of the shipping papers and left another copy with the box. I then took a photo…”
- *Air carrier flight crew reported mistakes in flight release documentation relating to the number of jumpseaters on board.* → “We were told we had 2 jumpseaters. We had two jumpseaters. We showed 2 jumpseaters on the final Weight and balance. We noticed at cruise that the release only listed one jumpseater. We notified company and got time and initials for adding j…”
- *Air carrier Captain reported deviating from final approach due to proximity of aircraft approaching parallel runway at SFO airport.* → “We had been monitoring the wind event and ATIS wind changes enroute from ZZZ to SFO. Wind changed from a headwind for Runway 28 to 020 [at] 10 kts. Crossing ZZZZZ at 11;000 feet we were assigned the visual to 28R. On a vector we were reassi…”

What this measures: paraphrase-to-passage retrieval and exact-identifier retrieval,
both with objective labels. What it does not: judged precedent relevance for
briefing-style queries — that is the Sprint 5 golden set.
