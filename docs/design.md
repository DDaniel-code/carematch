# CareMatch design (draft v0 — to be tuned on real data)

Question we answer: *for this service, near this place, which facilities have the strongest traceable public evidence,
and what still has to be confirmed by phone?* We do not claim real-time availability or clinical quality.

## Users and workflow

Primary user: a community health worker or NGO referral coordinator (non-technical, often on a phone).

1. Pick a service (dialysis, emergency C-section, NICU, trauma/emergency, cardiac surgery, MRI, …) and type a place
   (city, district, 6-digit PIN, or lat/lon).
2. Get 0–3 recommendation cards. Each card: name, distance, evidence tier, 1–2 quoted source sentences with the field they came from,
   what is uncertain, phone number, and "ask when you call" questions.
3. Optional drawer: all evidence rows, data-quality flags, and why other nearby facilities ranked lower.

## Pipeline (Databricks notebooks, writes Delta tables in our own catalog)

| Step | Output table | What it does |
| --- | --- | --- |
| 01 clean | `facilities_clean` | parse JSON-array fields, canonical city/state names, attributes for cards (phone, type, capacity, doctors, address, PIN) |
| 02 location | `facility_location` | coordinate validity, PIN→state check against India Post directory, city-median outlier check → `location_confidence` high / medium / low |
| 03 identity | `facility_groups` | merge rows with the same normalized name within ~1 km; flag rows whose text mentions several facilities |
| 04 evidence | `facility_service_evidence` | one row per facility × service × field × snippet, with matched term, term strength, polarity |
| 05 lookup | `pin_centroids` | PIN → centroid of geocoded post offices, district, state, spread (km) |

Query time (Python, used by notebook and app): resolve location → compute distance to every facility with evidence → tier → rank → explain.

## Service vocabulary

Each service has terms in three strengths, matched per field (whole-word, case-insensitive, camelCase split):

- **specific**: the service itself (e.g. dialysis: `dialysis`, `haemodialysis`, `hemodialysis`, `dialysis machine`, `CRRT`)
- **supporting**: the department or prerequisites (e.g. `nephrology`, `nephrologist`)
- **umbrella**: broad specialty only (e.g. `internal medicine`) — never enough on its own

## Evidence tiers (per facility × service)

| Tier | Rule (draft) |
| --- | --- |
| **Strong** | a *specific* term in `procedure` or `equipment`, **and** corroboration in a second field (`capability`, `specialties` supporting term, or description) |
| **Moderate** | a *specific* term in exactly one structured field (`procedure`, `equipment`, `capability`) |
| **Weak** | only *supporting/umbrella* terms, or *specific* term only in `description` |
| **None** | no match |

Only Strong and Moderate are recommended. Weak matches are listed separately as "mentioned, unverified".
Negative/planned statements ("no dialysis", "coming soon") are detected with a narrow, tested pattern list and
remove the claim instead of flagging a vague conflict.

Downgrade one tier (and say why) when: location confidence is low; the record looks merged with another facility;
facility type contradicts the service (e.g. dentist claiming NICU).

## Ranking

1. Distance bands from the user's location: ≤ 25 km, ≤ 75 km, ≤ 150 km, ≤ 300 km.
2. Find the nearest band that contains at least one Strong or Moderate facility.
3. Inside that band order by tier, then distance, then evidence count; take up to 3 distinct facilities.
4. If a Strong facility exists in the next band and the chosen band has only Moderate ones, show it as a 4th
   "farther but stronger evidence" option.
5. Nothing within 300 km → say so and show the nearest Weak mentions, clearly labelled.

Why bands and not a weighted score: a single number hides the trade-off. Bands make the rule explainable in one sentence
("nearest area with credible evidence, then strongest evidence first") and the cut-offs can be shown to the user.

## Explanation template (every claim cites a field and snippet)

> **{name}** — {distance} km, {tier} evidence.
> Records say: "{snippet}" ({field}); "{snippet 2}" ({field}).
> Uncertain: {flags in plain words}. Call {phone} and ask: {service-specific questions}.

## Evaluation

- 30–50 hand-labelled queries (service × place, incl. rural and "no good answer" cases).
- Metrics: tier precision on a reviewed sample, citation-supports-claim rate, duplicate rate in top 3,
  share of answers with a computable distance, correct abstention.

## Open questions

- Databricks Apps availability on Free Edition (fallback: notebook with widgets + AI/BI dashboard).
- Road travel time is out of scope; distances are straight-line and labelled as such.
