# Facilities data profile (Genie audit, 2026-11-21)

Source: `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities` (10,088 rows).
Numbers below were produced by Databricks Genie (Assistant) running read-only SQL. Each section notes
where the query itself limits the conclusion ("Caveat"). Treat these as profiling signals, not verified facts.

## 1. Field formats

| Column | Actual format |
| --- | --- |
| `specialties` | JSON array of camelCase enum strings, duplicates inside the array |
| `procedure`, `equipment`, `capability` | JSON arrays of free-text strings; may be `[]`; `capability` may be literal `null` |
| `source_urls` | JSON array of URLs that can contain `null` elements |
| `phone_numbers` | JSON array of phone strings, same number repeated up to 10x |
| `coordinates` | single GeoJSON Point object `{"coordinates":[lon,lat],"type":"Point"}` |

## 2. Coverage (% non-empty; `''`, `[]`, `null`, `None` treated as empty)

| Column | % | Column | % |
| --- | ---: | --- | ---: |
| specialties | 98.9 | description | 99.2 |
| procedure | 91.4 | numberDoctors | 36.0 |
| equipment | 76.2 | capacity | 25.0 |
| capability | 98.6 | yearEstablished | 47.6 |
| source_urls | 98.8 | recency_of_page_update | 35.2 |
| phone_numbers | 96.6 | coordinates | 98.8 |

Implication: `capacity` / `numberDoctors` can only be optional context, never a required ranking input.

## 3. Identity keys

- `unique_id`: 10,077 distinct across 10,088 rows (11 IDs appear twice). Matches Charlie's profile.
- `cluster_id`: 9,959 distinct non-empty; 9,948 singleton clusters, 11 clusters of 2; 118 rows empty. Not useful for dedup.
- 18 duplicate `(lower(name), lower(city))` pairs covering 38 rows, e.g. `care dental hospital`/bangalore,
  `durgapur sub divisional hospital`/durgapur, `government medical college, thiruvananthapuram`; plus 4 rows whose name is the string `null`.
  These have different `unique_id`s, so search keeps them as separate candidates -> ranking must dedupe before Top 3.

## 4. Location quality (flat `latitude` / `longitude`)

- Null lat/lon 118 · exactly (0,0) 0 · outside India box (lat 6–37, lon 68–98) 6
- Empty postcode 66 · postcode not 6 digits 250 (2.5%)
- Caveat: at least one sampled `coordinates` GeoJSON disagreed with the flat columns (lon/lat outside India). Count of disagreements not yet measured.

## 5. Postcode vs state

- 9,568 facilities have a postcode found in the PIN directory: 9,101 agree, 467 disagree (4.9%).
- Caveat: the query collapsed each PIN to `MIN(statename)`, hiding PINs that map to several states; and it compared raw upper-case
  strings, so part of the 467 is spelling (`Nct Of Delhi` vs `DELHI`) or a city stored in the state field (Mumbai, Pune, Latur).
  The true mismatch rate is lower than 4.9%. Real conflicts exist (e.g. a Telangana facility with Delhi PIN 110002).

## 6. City name variants

No case/whitespace variants, but semantic splits that the search must merge:

| Canonical | Variants (rows) |
| --- | --- |
| Bengaluru | Bangalore 204 + Bengaluru 110 |
| Gurugram | Gurgaon 82 + Gurugram 65 |
| Delhi | New Delhi 146 + Delhi 133 |
| Thiruvananthapuram | Thiruvananthapuram 52 + Trivandrum 20 |
| Kochi | Kochi 44 + Cochin 11 |
| Visakhapatnam | Visakhapatnam 53 + Vizag 1 |

Legacy names Bombay / Madras / Calcutta do not appear.

## 7. Service recall by column

| Service (regex) | specialties | procedure | equipment | capability | description |
| --- | ---: | ---: | ---: | ---: | ---: |
| dialysis (`dialysis\|haemodialysis\|hemodialysis\|nephrology`) | 2,203 | 795 | 475 | 1,299 | 202 |
| C-section (`caesarean\|cesarean\|c-section\|lscs\|obstetric`) | 4,535 | 1,007 | 71 | 2,232 | 295 |
| NICU (`nicu\|neonatal intensive\|newborn intensive`) | 2 | 78 | 242 | 602 | 77 |
| trauma (`trauma\|emergency\|casualty`) | 2,499 | 1,389 | 289 | 3,486 | 540 |

- Every column adds recall; `specialties` almost never encodes NICU.
- Caveat: these patterns are broad. `obstetric` matches the specialty `obstetricsAndGynecology` (not a C-section claim),
  `nephrology` is not dialysis, and `emergency` is not trauma care. Strict counts (e.g. `caesarean|cesarean|c-section|lscs` only) are still needed;
  in Bihar the strict C-section pattern hits only 12 of 258 facilities.

## 8. Weak vs strong evidence (dialysis)

- 968 facilities mention dialysis terms in `equipment` or `procedure`; 202 in `description`; only 84 are description-only.
- Description-only hits are mostly specialty lists ("Specialties: ... Nephrology", "Consultant – Nephrology"), not operational claims.
  -> description-only should be weak evidence.

## 9. Negations

- Genie's pattern (`no dialysis|not available|referred to|coming soon` within 100 chars of a service word) found 0 hits.
- Caveat: this pattern is narrow, so it does not prove negations are absent. Search's own heuristic is much broader
  (any `no/not/may/soon` in the clause) and produces false negatives such as "dialysis unit with no waiting time".
  Both need calibrating on real flagged snippets.

## 10. Facility type

- `organization_type` = `facility` for 10,000 rows (uninformative).
- `facilityTypeId`: hospital 5,637 · clinic 3,782 · dentist 490 · empty 67 · null 59 · doctor 21 · farmacy 10 · pharmacy 2, plus
  1-count junk values (URLs, coordinates, hashes) from column shifts.
- 3 rows are column-shifted outright: prose in `unique_id` and a JSON null, a GeoJSON point or a number in `specialties`.
  `CareIndex` sets them aside before anything is located or assessed (`textutil.audit_source_rows`: `specialties` must be
  empty or a JSON list of strings) and reports the count as `index.data_quality` (10,088 input, 10,085 accepted,
  3 quarantined). None of the three had evidence for any of the nine services.
- 106 facilities typed clinic/dentist/doctor or capacity < 10 claim cardiac surgery, NICU or dialysis. Some are mislabeled hospitals
  (a "clinic" with 304 beds), others diagnostics centres. Type alone cannot gate; combine with evidence.

## 11. Evidence depth

- 118 facilities have no source URL.
- Caveat: URL counts were computed by counting commas, which includes `null` array elements, so the per-facility counts are inflated
  (the "no facility has exactly 1 URL" result is likely an artefact).
- `recency_of_page_update`: 64.8% missing; known values cluster around 2025-12-18 … 2025-12-21 (a December 2025 crawl).

## 12. Geography

Top states: Maharashtra 1,575 · Gujarat 981 · UP 919 · Tamil Nadu 780 · Karnataka 529 · Kerala 483 · West Bengal 477 ·
Punjab 469 · Haryana 462 · Telangana 421 · … · Bihar 258 · Jharkhand 156 · Assam 117.

| State | Facilities | Dialysis mentions | Strict C-section mentions |
| --- | ---: | ---: | ---: |
| Bihar | 258 | 80 | 12 |
| Jharkhand | 156 | 42 | 7 |
| Assam | 117 | 36 | 6 |
| Other 7 northeast states | 49 | 19 | 1 |

Rural/northeast queries will often have no strong nearby option; the product must say so instead of padding results.

## Implications for search and ranking

1. Match services across all five evidence fields with a per-service vocabulary; weight `equipment`/`procedure` above `description`.
2. Canonicalize city names (table 6); support PIN / coordinates so locations outside listed cities still work.
3. Do not rely on `unique_id` / `cluster_id` for dedup; dedupe by normalized name + proximity before Top 3.
4. Flag postcode/state conflicts and malformed postcodes as location uncertainty.
5. `capacity` / `numberDoctors` are optional context only.
6. When no candidate clears the evidence bar, return fewer than 3 (or none) with the reason.
