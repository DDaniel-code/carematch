# Optional preference model (2026-11-21)

The default answer ranks credible facilities by evidence, then distance. A health worker can also say what matters
for this patient: **how urgent it is** and **whether cost matters**. The preference model re-orders the *same* credible
options; it never adds a facility the default would not consider, never recommends Weak evidence, and never turns an
honest "nothing within 300 km" into an answer.

Code: [`carematch/decision.py`](../carematch/decision.py), wired into `recommend(..., preferences=...)` and the app's
"Preferences (optional)" panel. Evaluation: `python -m scripts.run_pref_eval`.

## Inputs

| Preference | Options | Effect |
| --- | --- | --- |
| Urgency | default · time-critical · can travel | changes the weights; *can travel* also looks one distance band further, capped at 2× the nearest credible option's distance or +100 km |
| Cost | any · low cost | *low cost* adds a cost component; facilities whose record says nothing about cost are **listed separately**, never scored as expensive |

Default (both unset) returns exactly the evidence-then-distance ranking: the 38 golden queries give identical results
before and after this change (checked by the evaluation script against `eval/results.csv`).

## Score

`score = Σ weight × component`, weights sum to 1. Each component is in [0, 1] and is shown on the card with its reason.

| Component | How it is computed | Cited text |
| --- | --- | --- |
| Evidence | Strong 1.0, Moderate 0.6 | the evidence quote and its column |
| Travel | estimated drive time = km × 1.4 / speed (40 km/h; 25 km/h in hill states); weight = exp(−extra minutes vs the nearest credible option / τ), τ = max(base, scale × nearest option's drive time) | none (an estimate, labelled as such) |
| Readiness | share of service-specific signals the record mentions, e.g. C-section: anaesthesia, blood bank, operation theatre, 24x7, newborn care; trauma: ICU, blood bank, CT, 24x7, ambulance, neuro/ortho surgery | each signal's quote and column; 24x7 laboratories, pharmacies, canteens do not count |
| Cost (low-cost only) | covered (public operator, government scheme such as PM-JAY / state schemes / ESIC / CGHS, free or charitable care) 1.0; cashless / insurance 0.6; not documented → listed separately | the quote and column (or `operatorTypeId` = public) |

| Urgency | Evidence | Travel | Readiness | τ base / scale |
| --- | ---: | ---: | ---: | --- |
| Time-critical | 0.35 | 0.45 | 0.20 | 45 min / 0.5 |
| Default weights (used when only cost is set) | 0.45 | 0.30 | 0.25 | 120 min / 1.0 |
| Can travel | 0.55 | 0.10 | 0.35 | 480 min / 2.0 |

With *low cost*, these weights are scaled by 0.7 and cost takes 0.3.

**These are ranking weights built from stated assumptions, not probabilities.** The app says so next to every score
and never describes a score as a chance of being treated or of survival.

### Two design choices made after testing

- **Travel is relative to the nearest credible option.** An absolute decay (exp(−minutes/45)) gave every option ~0 in
  remote districts where the nearest is 5 hours away; the ranking then followed readiness alone and sent a
  time-critical trauma patient from Kohima to Assam (213 km) instead of Imphal (99 km). Relative extra time fixes it.
- **The decay scale grows with the nearest option's drive time,** so the second and third choices in remote places
  still follow distance (Kohima trauma, time-critical: Imphal 99 km → Churachandpur 156 km → Assam 214 km).

## Transparency on every re-ordered answer

When the preference pick is farther than the default pick, the result carries a **trade-off note** that names what was
given up and quotes what was gained, e.g. (dialysis, Kohima, low cost):

> Eden Medical Centre is 70.3 km nearer (its cost is not documented, which does not mean it is expensive). This option
> was preferred because its record documents affordable care: "public" [operator type] …

A ninth quality check runs in preference mode: **every preference reason that cites the record quotes it word for word.**

## Evaluation on the 38 golden queries

| Variant | Quality checks | Top-1 changed vs default | Median km to top-1 | Top-1 Strong | Top-1 cost documented |
| --- | ---: | ---: | ---: | ---: | ---: |
| Default | 38/38 | — | 31.5 | 32/36 | 0 (not used) |
| Time-critical | 38/38 | 17 | 31.5 | 30/36 | 14 |
| Can travel | 38/38 | 20 | 59.2 | 33/36 | 14 |
| Low cost | 38/38 | 28 | 77.3 | 29/36 | 35/36 |
| Time-critical + low cost | 38/38 | 28 | 77.3 | 27/36 | 35/36 |

All variants answer the same 36 queries and abstain on the same 2 (Port Blair); none recommends Weak evidence.
Latency p95 ≈ 100 ms (default 77 ms). Per-query results: `eval/preference_results.csv`.

### Behaviour worth knowing (and showing)

| Variant | What happens | Size |
| --- | --- | --- |
| Time-critical | top-1 is sometimes slightly farther because it documents readiness, e.g. CT in Kolkata 0.2 → 1.9 km for "128 Slice Dual Energy CT Scan" and "24x7 emergency care" | 12 queries, at most +8.1 km |
| Time-critical | top-1 sometimes switches from Strong to a nearer Moderate (PIN 764020 emergency: 129.5 → 108 km) | 2 queries |
| Can travel | goes further for stronger evidence or readiness (MRI, Darbhanga: Moderate at 1 km → Strong at 51 km) | 17 queries, at most +115 km |
| Low cost | goes further for documented free / scheme care (CT, PIN 845401: 16 km → 123 km, "CGHS empanelled") | 25 queries, at most +107 km |

### Failure cases found and fixed

| Case | Problem | Fix |
| --- | --- | --- |
| Trauma, Kohima, time-critical | absolute travel decay flattened to 0; picked Assam (213 km) over Imphal (99 km) | relative travel time + scaled decay |
| Dialysis, Kohima | "Operates a 24x7 microbiology laboratory" counted as 24x7 readiness | non-clinical 24x7 services excluded |
| NICU, PIN 835207, can travel | top-1 moved from 87 km to 290 km for readiness signals | "can travel" capped at 2× nearest or +100 km |
| Burn care, Mon, low cost | no option documents cost; the same facility appeared both ranked and in the "cost unknown" list, breaking numbering | fall back to everyone (labelled) and list nothing separately |

## Limits

- Weights, speeds and decay scales are assumptions, not estimates from outcome data (the dataset has none); they are
  printed with every answer and are easy to change.
- Readiness counts mentions, not verified capacity; absence of a mention is not absence of the service.
- Cost is a category from the record, not a price; 73% of records (7,337 of 10,088) say nothing about cost (16% covered, 11% insured), which is why
  "not documented" is kept separate.
- Drive times are straight-line estimates, not routes.
