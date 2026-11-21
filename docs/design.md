# CareMatch design (v1, implemented)

Question we answer: *for this service, near this place, which facilities have the strongest traceable public evidence,
and what still has to be confirmed by phone?* We do not claim real-time availability or clinical quality.

## Users and workflow

Primary user: a community health worker or NGO referral coordinator (non-technical, often on a phone).

1. Pick a service and type a place: city, district, 6-digit PIN, or "lat, lon" (optionally "Aurangabad, Bihar").
2. Get 0–3 cards. Each card: name, straight-line distance, evidence tier, 1–3 quoted sentences with the column they came
   from, what is uncertain, phone, and "ask when you call" questions.
3. When nothing credible is near, the answer says so and shows the nearest option beyond 300 km, labelled.

## Code map

| Module | Job |
| --- | --- |
| `carematch/services.py` | per-service vocabulary (direct / related / excluded terms), negation and referral patterns, call questions |
| `carematch/evidence.py` | classify each claim sentence, assign Strong / Moderate / Weak / None with reasons and caps |
| `carematch/geo.py` | resolve user location; judge each facility's position (coordinates vs PIN vs city) |
| `carematch/recommend.py` | distance bands, ranking, duplicate merge, result cards |
| `carematch/render.py` | plain-text rendering; `scripts/ask.py` CLI |

## 1. Evidence tiers

See [evidence_calibration.md](evidence_calibration.md) for the rules, counts and calibration log.

## 2. Locations

**User input.** Coordinates → used as is. PIN → centre of its geocoded post offices (precision ≈ half their spread);
unknown PIN → centre of PINs sharing its first 4 digits, flagged approximate. Name → city (median of facilities listed in
that city) or district (median of its PIN centres); same-name places in other states are offered as alternatives.

**Cleaning the PIN directory.** Some post offices were geocoded to a same-named place in another state
(Aurangabad, Bihar PINs placed in Aurangabad, Maharashtra, ~1,000 km away). PIN codes sharing leading digits belong to one
postal region, so a centre > 400 km from its 2-digit region median or > 150 km from its 3-digit median is discarded
(1,227 PIN centres dropped).

**Facility position: three-signal vote.** For each facility we compare its coordinates, its PIN centre, and the median of
other facilities listed in its city (radius 25–60 km depending on city size):

| Situation | Action | Facilities |
| --- | --- | ---: |
| all agree / no conflict | use coordinates, confidence high | 8,017 |
| PIN and city agree, coordinates far off | use PIN centre, confidence approximate | 434 |
| coordinates and city agree, PIN far off | use coordinates, flag PIN, confidence medium | 131 |
| cannot tell which is right | confidence low, **distance = farthest candidate** (conservative), Strong → Moderate | 834 |
| no coordinates | PIN centre (approximate) or city centre (low) | ~100 |

## 3. Ranking

1. Only Strong and Moderate facilities are recommended.
2. Distance bands from the user: 25, 75, 150, 300 km. Use the nearest band with any recommendable facility.
3. Inside the band: tier, then distance, then amount of evidence. Listings with the same name within 2 km are merged.
4. If the band only has Moderate options and a Strong one exists in the next band, it is added as
   "farther, stronger evidence".
5. Nothing within 300 km → no recommendation; show the nearest credible facility beyond, and weak mentions within 75 km,
   each clearly labelled.

Why bands instead of one weighted score: the trade-off between distance and evidence is visible and explainable in one
sentence ("nearest area with credible evidence, then strongest evidence first"). A single number would hide it.

## Known limits

- Straight-line distance, not road travel time.
- English-only patterns; claims may describe another facility when a record merged two sources.
- Weak/none does not mean a facility lacks the service — only that the public text does not show it.
