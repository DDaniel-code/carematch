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
| `safety_note` | emergency services (C-section, trauma, emergency, NICU, burn), nearest **and price** mode: call-ahead / 108 message |
| `stronger_option_nearby` | nearest mode, emergency service, top result is Moderate and a Strong option is within `max_extra_km`: `{facility_id, name, distance_km, note}` |
| `no_ranked_reason` | **new**: set when every credible option nearby is unresolved (mixed record or uncertain location). Then `results == []`, `ranked_count == 0`, `nearest_credible_km` and `band_km` are `null`, the flagged cards stay in `branch_unresolved` / `location_uncertain` with their `not_ranked_because`, and `result.action_advice` repeats this reason. Show it instead of "no facility found": credible options exist, they just cannot be pinned to one branch |

`sort` (price mode only):

| Key | Meaning |
| --- | --- |
| `price_comparison` | `{unit, conditions, budget_km, comparable_quotes, ranked_by: 'price'|'distance'|null, cheapest_claim: bool, safety_pinned: facility_id|null, note}`; `ranked_by` is `null` only with `no_ranked_reason` |
| `price_unknown_nearby` | credible options within the budget with **no documented price** (never dropped) |
| `price_not_comparable` | options with a price that cannot be compared (`card.not_comparable_because`: unit not stated / different unit / different eligibility or conditions: … / free only with conditions: …) |

Show `price_comparison.note` verbatim; only say "cheapest" when `cheapest_claim` is true.

Price-mode cards that show a price also carry `card.price_comparable` (bool) and, when false, `card.not_comparable_because`,
so a quote shown in a distance-ordered list is always labelled as compared or not.

## Ordering rules

- **nearest**: credible, branch-resolved options with a certain location, by conservative straight-line distance
  (farthest plausible position when location is uncertain). Emergency services: a record that also states the service
  is not available never goes first while a clean option exists within `max_extra_km` (`card.safety_reordered = True`).
- **Both modes, all unresolved**: if no credible option nearby is branch-resolved with a certain location, nothing is
  ranked (`results == []`, `sort.no_ranked_reason`); the flagged cards are listed, never promoted to #1.
- **price**: candidates = same ranked set, within `nearest_credible_km + max_extra_km`. Prices are compared only when
  they are **like-for-like**: same service, same stated unit **and the same set of conditions** (eligibility such as BPL
  or members only, concessional rate, scheme / insurance, inclusions, discounted offer, dated price). The largest such
  group is compared (`price_comparison.unit` / `.conditions`). A concessional BPL rate and an ordinary rate share a unit
  but not who can get them, so they are not ranked against each other: with fewer than 2 like-for-like quotes the list is
  ordered by distance (`ranked_by = 'distance'`) and every quote is labelled on its card. With ≥ 2: ordered by the upper
  documented amount (exact or range max; an upper bound counts as its maximum; lower bounds sort last).
  `cheapest_claim` is true only when the top quote's maximum is below every other like-for-like quote's minimum.
- **price, urgent services** (C-section, trauma, emergency, NICU, burn): the nearest safe option (certain location, no
  "not available" statement) stays #1 whatever its price (`card.safety_pinned = True`,
  `price_comparison.safety_pinned`); price orders only the options after it.

## New card keys (every mode)

`card.price_info`: `None`, or

```json
{"kind": "patient_price", "bound": "exact|range|upper_bound|lower_bound|free",
 "amount_min_inr": 1200, "amount_max_inr": 1800, "currency": "INR",
 "unit": "per_session|per_scan|per_day|per_procedure|per_month|package|unspecified",
 "conditions": ["concessional / subsidised rate", "restricted eligibility", "inclusions stated", "scheme / insurance condition", "discounted offer", "dated price"],
 "scope": "dialysis", "field": "capability", "quote": "<exact fragment>", "other_price_quotes": 0}
```

`upper_bound` has `amount_min_inr = null`; `lower_bound` has `amount_max_inr = null`.

`card.price_context`: list of money mentions that are **not** patient prices, each
`{kind: 'insurer_coverage'|'capital_or_equipment', amounts_inr, field, quote, note: 'not a patient price'}`.
Show them, if at all, labelled as not a price (e.g. "PM-JAY cover up to ₹5 lakh per family — not a price").

Card keys used only in sort modes: `not_ranked_because`, `distance_range_km`, `not_comparable_because`,
`price_comparable`, `safety_reordered`, `safety_pinned`, `why_not` (runner-ups).

## Never inferred (enforced by tests)

Public operator ≠ free · package ≠ per session · equipment / building cost ≠ patient fee · insurer cover ≠ price ·
one quote ≠ cheapest · concessional / restricted-eligibility rate ≠ ordinary rate · "infection-free", "hassle-free",
"pain-free" ≠ free of charge · a price is read only from a fragment that names the service itself.

## Quality checks

- Every price quote (price_info and price_context) appears word for word in the facility record.
- Nearest and price mode: no ranked card is a possible mixed record or has an uncertain location; if none qualifies,
  nothing is ranked and `no_ranked_reason` is set.
- Nearest mode: ordered by distance (after an emergency safety move).
- Price mode: only like-for-like prices (same unit and conditions) are price-ordered, within the budget; an urgent
  service's safety-pinned card may only be #1; no "cheapest" from fewer than two comparable quotes.

## Changelog

- **Fixes after Codex review of 0cb8267**: (1) all-unresolved candidates no longer fall back to ranking a mixed record
  #1: `results == []` + `no_ranked_reason`; (2) prices are compared only within the same unit **and** conditions (a
  BPL concessional Rs 300 per session is no longer ranked against an ordinary Rs 1,500 per session); (3) urgent
  services keep the nearest safe option first in price mode too (`safety_pinned`); (4) "infection-free dialysis" and
  similar "X-free" phrases are no longer read as a free price. New condition label `restricted eligibility`.

## Data reality (worth showing)

Patient prices are rare: across 10,088 records, 764 fragments mention money but only a handful are service-specific
patient prices. Example, dialysis near Nagpur (price mode, 25 km): 0 comparable quotes, so options are shown nearest
first. The only dialysis price quote, "Offers dialysis services at concessional pricing (Rs. 350 or less per session)
including blood tubing and dialyser", belongs to "Wockhardt Hospital Nagpur", whose map position and PIN are in Mumbai
and whose record describes Fortis hospitals; it is listed under `branch_unresolved` with that reason, not ranked.
