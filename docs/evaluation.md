# Evaluation (2026-11-21)

Reproduce: `python -m scripts.run_eval` (writes `eval/results.csv`, `eval/review_sheet.csv`, `eval/summary.json`;
exits non-zero if a hard gate fails). Invariant tests: `python -m unittest discover -s tests`
(`CAREMATCH_FULL_EVAL=1` runs every golden query).

## Golden set

38 queries in [`eval/queries.csv`](../eval/queries.csv): 9 services × 4 place types — metro, tier-2 city, rural PIN code,
remote / northeast — plus a same-name district ("Aurangabad, Bihar") and two island queries (Port Blair) where the honest
answer is "nothing credible within 300 km".

## Automatic results

| Metric | Result | Gate |
| --- | --- | --- |
| Quality review passed (8 checks per query, shown in the app) | 38 / 38 | all |
| Citation fidelity: quotes found word for word in the named column of the facility record | 248 / 248 (100%) | 100% |
| Duplicate facility in a top 3 | 0 | 0 |
| Same input → identical output | yes (invariant test) | yes |
| Answered within 300 km | 36; honest "nothing within 300 km" for 2 (Port Blair) | report |
| Recommendations shown | 104 (89 Strong, 15 Moderate) | report |
| Query latency, warm index | p50 13 ms, p95 78 ms | < 100 ms |

Median straight-line distance to the top recommendation by place type:

| Place type | Queries | Median km to top-1 |
| --- | ---: | ---: |
| Metro | 9 | 2.4 |
| Tier-2 city | 9 | 1.3 |
| Rural PIN code | 8 | 113 |
| Remote / northeast | 11 | 117 (2 with no answer) |

The gap between cities (1–3 km) and rural / remote places (~100 km) is the access problem the challenge describes, and it
is visible directly in our output.

## Review of top-1 answers: two independent model reviewers + human adjudication

Reading 36 records by hand is slow, so review is layered (`eval/review_sheet.csv`):

1. **Engine-author model (Claude)** pre-judges each top-1 quote (`model_*`).
2. **Independent second model (ChatGPT)** judges the same quote *and reads the whole facility record* (`xcheck_*`).
3. **Humans adjudicate only where the two disagree**, plus a random spot check of agreements, using
   `eval/review.html` — one page with the card, every quote, warnings and both opinions (`python -m scripts.make_review_page`).

| | Claude | ChatGPT |
| --- | --- | --- |
| Quote supports the service | 32 yes, 4 partly, 0 no | 27 yes, 9 partly, 0 no |
| One real facility | 32 yes, 3 merged, 1 duplicate | 32 yes, 3 merged, 1 duplicate |
| Agreement on both questions | 31 / 36 | |

No reviewer found a quote that contradicts the service. The remaining 5 disagreements (q05–q08, q20) are all the same
question: a quote proves caesarean deliveries / emergency care, not *emergency readiness right now* or *24x7 cover*.

### Human adjudication (9 rows: 5 disagreements + 4 random agreements)

| Row | Decision | Note |
| --- | --- | --- |
| q05–q08 (C-section) | partly — sided with ChatGPT | Split into two questions: the quote proves the hospital performs C-sections (yes); it does not prove emergency readiness now (unknown → confirm by phone). Tier-2 and remote places deserve stricter checking because there are fewer alternatives. |
| q20 (emergency) | yes — sided with Claude | "24/7" and "24x7" are the same claim. |
| q19, q23, q33, q35 (spot checks) | yes | q33: a partnership is not outsourcing, but equipment must be confirmed by phone. q35: an approximate PIN should get 3 options over a wider radius. |

Product changes from the adjudication: partnership claims stay direct but carry a "confirm the equipment is on site"
warning; an approximate location (PIN area, district) starts the search at ≥ 2× its uncertainty and widens until there are
3 options, listing nearer finds first; every answer now carries an action line that is stricter when alternatives are few.

### What the cross-check found, and what we changed

| Finding (ChatGPT, verified against the data) | Fix |
| --- | --- |
| Sarla Hospital, Mumbai has two rows with the same PIN; one has coordinates 600 km away, so the 2 km duplicate rule missed it | duplicate groups now use same name + (same PIN **or** within 2 km), across the whole dataset |
| SPARSH Hennur Road record also describes the Infantry Road and Sarjapur Road branches | whole-record check for other branches of the same brand |
| CIMS Ahmedabad record contains 5 statements about Life Care Hospital and 4 placing it in Vadodara | whole-record check: another facility named in ≥ 3 statements, or another city in ≥ 3 |
| North Kashmir Nursing Home (Handwara) record contains Kashmir Nursing Home, Srinagar statements | same whole-record check |
| "Emergency C-section" and "24x7 emergency" overstated what a quote can prove | services relabelled "C-section (caesarean delivery)" and "Emergency care"; each service now states what the records can and cannot show |

The whole-record check flags 1,216 of 10,088 records (12%); flagged cards say "some claims may describe a different
facility" and quote the reason. It does not change the tier unless the service claims themselves name another place.

## Errors found by this evaluation and fixed

| Query | Problem | Fix |
| --- | --- | --- |
| Cardiac surgery @ Bhopal | top quote was "General surgeries are performed **excluding** cardiothoracic and vascular surgery" | `excluding / except / other than` added to negation |
| Emergency @ PIN 764020 | recommended "Patra **Dental** Clinic" (type field said only "clinic") | facility names that indicate a specialist (dental, eye, homoeo, ayurveda, rehab, …) cap the tier at Weak |

## Sensitivity

Each variant re-runs the golden set and compares with the baseline:

| Variant | Same top-1 | Mean top-3 overlap (Jaccard) |
| --- | ---: | ---: |
| Distance bands 20 / 60 / 120 / 250 km | 94.7% | 0.90 |
| Distance bands 30 / 90 / 180 / 350 km | 97.4% | 0.96 |
| Strong requires ≥ 3 distinct claims (instead of 2) | 73.7% | 0.64 |

Reading: the answer barely depends on the exact band cut-offs. It depends more on how much evidence we demand for
"Strong", which is why the product shows tiers and the quotes themselves rather than a precise score.

## Quality checks run on every query

1. At most 3 recommendations, all Strong or Moderate.
2. No facility listed twice.
3. Every quote appears word for word in the facility record.
4. Every recommendation cites at least one quote.
5. Distances are positive or explicitly unknown (never a fake 0 km).
6. Ordered by tier then distance; all within the search radius.
7. Only recommendations are numbered; extras and runner-ups are labelled.
8. Every recommendation says what to confirm by phone; disclaimer present.
