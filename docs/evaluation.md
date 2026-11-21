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
| Citation fidelity: quotes found word for word in the named column of the facility record | 231 / 231 (100%) | 100% |
| Duplicate facility in a top 3 | 0 | 0 |
| Same input → identical output | yes (invariant test) | yes |
| Answered within 300 km | 36; honest "nothing within 300 km" for 2 (Port Blair) | report |
| Recommendations shown | 98 (83 Strong, 15 Moderate) | report |
| Query latency, warm index | p50 13 ms, p95 74 ms | < 100 ms |

Median straight-line distance to the top recommendation by place type:

| Place type | Queries | Median km to top-1 |
| --- | ---: | ---: |
| Metro | 9 | 2.4 |
| Tier-2 city | 9 | 1.3 |
| Rural PIN code | 8 | 92 |
| Remote / northeast | 11 | 117 (2 with no answer) |

The gap between cities (1–3 km) and rural / remote places (~100 km) is the access problem the challenge describes, and it
is visible directly in our output.

## Human review of top-1 answers

`eval/review_sheet.csv` lists each top-1 quote. The model pre-filled a judgement and reason (`model_*` columns);
**the `human_*` columns are for the team and are the numbers we report.**

| | Model pre-judgement | Human (to fill) |
| --- | --- | --- |
| Quote directly supports the service | 32 / 36 yes, 4 partly, 0 no | |
| Quote is about this one facility | 36 / 36 (no merge signal) | |

The 4 "partly" cases are labelled honestly in the product: two are department-list mentions shown as Moderate, one is
neuro-trauma for a trauma query, one is a transcatheter valve device for a cardiac-surgery query.

## Errors found by this evaluation and fixed

| Query | Problem | Fix |
| --- | --- | --- |
| Cardiac surgery @ Bhopal | top quote was "General surgeries are performed **excluding** cardiothoracic and vascular surgery" | `excluding / except / other than` added to negation |
| Emergency @ PIN 764020 | recommended "Patra **Dental** Clinic" (type field said only "clinic") | facility names that indicate a specialist (dental, eye, homoeo, ayurveda, rehab, …) cap the tier at Weak |

## Sensitivity

Each variant re-runs the golden set and compares with the baseline:

| Variant | Same top-1 | Mean top-3 overlap (Jaccard) |
| --- | ---: | ---: |
| Distance bands 20 / 60 / 120 / 250 km | 94.7% | 0.88 |
| Distance bands 30 / 90 / 180 / 350 km | 97.4% | 0.92 |
| Strong requires ≥ 3 distinct claims (instead of 2) | 73.7% | 0.67 |

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
