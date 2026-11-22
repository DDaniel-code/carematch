# Sort modes and price evidence: engine contract (contract_version 1.1, additive)

For the app (Main). Engine code: `carematch/recommend.py` (`_sort_mode`), `carematch/price.py`, checks in
`carematch/review.py`. Nothing existing is renamed or removed; default output is unchanged apart from two new card keys.

## Call

```python
recommend(index, service, place,
          sort_mode='default',      # 'default' | 'nearest' | 'price'
          max_extra_km=25,          # price mode: how much farther than the nearest credible option to look (0..300)
          preferences=None)         # unchanged; cannot be combined with sort_mode != 'default' (ValueError)
```

Invalid `sort_mode` or `max_extra_km` raises `ValueError`. Safety gates are identical in every mode: only Strong /
Moderate evidence is ever ranked, the same location/merge downgrades apply, and "nothing within 300 km" stays an
honest no-answer (`results == []`, `nearest_beyond` as today).

## New result keys

| Key | When | Meaning |
| --- | --- | --- |
| `sort_mode` | always | the mode used |
| `sort` | mode ≠ default and there are results | dict below |
| `method` | always | text now describes the active mode |

`sort` (both modes):

| Key | Meaning |
| --- | --- |
| `mode`, `max_extra_km`, `nearest_credible_km`, `ranked_count`, `band_km` | context |
| `branch_unresolved` | cards **not ranked**: the record may mix facilities/branches (`card.not_ranked_because`) |
| `location_uncertain` | cards **not ranked**: address, PIN and map position disagree; `card.distance_range_km = [nearest, farthest]` |
| `safety_note` | nearest mode, emergency services (C-section, trauma, emergency, NICU, burn): call-ahead / 108 message |
| `stronger_option_nearby` | nearest mode, emergency service, top result is Moderate and a Strong option is within `max_extra_km`: `{facility_id, name, distance_km, note}` |

`sort` (price mode only):

| Key | Meaning |
| --- | --- |
| `price_comparison` | `{unit, budget_km, comparable_quotes, ranked_by: 'price'|'distance', cheapest_claim: bool, note}` |
| `price_unknown_nearby` | credible options within the budget with **no documented price** (never dropped) |
| `price_not_comparable` | options with a price that cannot be compared (`card.not_comparable_because`: unit not stated / different unit / free only with conditions) |

Show `price_comparison.note` verbatim; only say "cheapest" when `cheapest_claim` is true.

## Ordering rules

- **nearest**: credible, branch-resolved options with a certain location, by conservative straight-line distance
  (farthest plausible position when location is uncertain). Emergency services: a record that also states the service
  is not available never goes first while a clean option exists within `max_extra_km` (`card.safety_reordered = True`).
- **price**: candidates = same ranked set, within `nearest_credible_km + max_extra_km`. Prices are compared only when
  they are for this service and state the same unit (most common unit wins). With ≥ 2 comparable quotes: ordered by the
  upper documented amount (exact or range max; an upper bound counts as its maximum; lower bounds sort last). With
  fewer: ordered by distance, `ranked_by = 'distance'`, prices shown on cards. `cheapest_claim` is true only when the top
  quote's maximum is below every other comparable quote's minimum **and** all conditions match.

## New card keys (every mode)

`card.price_info`: `None`, or

```json
{"kind": "patient_price", "bound": "exact|range|upper_bound|lower_bound|free",
 "amount_min_inr": 1200, "amount_max_inr": 1800, "currency": "INR",
 "unit": "per_session|per_scan|per_day|per_procedure|per_month|package|unspecified",
 "conditions": ["concessional / subsidised rate", "inclusions stated", "scheme / insurance condition", "discounted offer", "dated price"],
 "scope": "dialysis", "field": "capability", "quote": "<exact fragment>", "other_price_quotes": 0}
```

`upper_bound` has `amount_min_inr = null`; `lower_bound` has `amount_max_inr = null`.

`card.price_context`: list of money mentions that are **not** patient prices, each
`{kind: 'insurer_coverage'|'capital_or_equipment', amounts_inr, field, quote, note: 'not a patient price'}`.
Show them, if at all, labelled as not a price (e.g. "PM-JAY cover up to ₹5 lakh per family — not a price").

Card keys used only in sort modes: `not_ranked_because`, `distance_range_km`, `not_comparable_because`,
`safety_reordered`, `why_not` (runner-ups).

## Never inferred (enforced by tests)

Public operator ≠ free · package ≠ per session · equipment / building cost ≠ patient fee · insurer cover ≠ price ·
one quote ≠ cheapest · a price is read only from a fragment that names the service itself.

## Quality checks added

- Every price quote (price_info and price_context) appears word for word in the facility record.
- Nearest mode: ordered by distance among branch-resolved, location-certain options.
- Price mode: same-unit prices only, within the budget, no "cheapest" from fewer than two comparable quotes.

## Data reality (worth showing)

Patient prices are rare: across 10,088 records, 764 fragments mention money but only a handful are service-specific
patient prices. Example, dialysis near Nagpur (price mode, 25 km): 0 comparable quotes, so options are shown nearest
first. The only dialysis price quote, "Offers dialysis services at concessional pricing (Rs. 350 or less per session)
including blood tubing and dialyser", belongs to "Wockhardt Hospital Nagpur", whose map position and PIN are in Mumbai
and whose record describes Fortis hospitals; it is listed under `branch_unresolved` with that reason, not ranked.
