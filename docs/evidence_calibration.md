# Evidence tiers: rules and calibration (2026-11-21)

Code: [`carematch/services.py`](../carematch/services.py) (vocabulary), [`carematch/evidence.py`](../carematch/evidence.py) (rules).
Reproduce: `python -m scripts.calibrate_evidence data/facilities.csv`.

## How a facility gets a tier for a service

The `procedure`, `equipment` and `capability` columns are JSON lists of short claims extracted from web pages
(median 10 / 2 / 18 claims per facility). We classify each claim on its own, so every statement we show
is one quoted sentence from a named column.

| Claim kind | Meaning | Example (real data) |
| --- | --- | --- |
| direct | names the service as something the facility does or has | "14 computerized dialysis machines" (equipment) |
| listed | service only appears inside a long department list (≥ 4 commas) | "Offers cardiology, cardiothoracic surgery, neurosurgery, …" |
| indirect | referral, outsourced, tie-up, planned, historical | "MRI facility (outsourced)", "MRI (via tie-up)" |
| negative | negation right next to the service term | "Caesarean section facility not available on-site; referrals to LNJP Kurukshetra" |
| mention | service named only in the free-text `description` | |
| related | department or prerequisite, not the service | specialty `nephrology` for dialysis |

| Tier | Rule |
| --- | --- |
| **Strong** | ≥ 2 *distinct* direct claims found in ≥ 2 columns, or ≥ 2 distinct direct claims + a related department |
| **Moderate** | at least one direct or listed claim |
| **Weak** | only indirect / mention / related evidence |
| **None** | nothing relevant, or only negative claims |

Caps: dentist / pharmacy / single-doctor listing → at most Weak. Small clinic (capacity unknown or < 20) for an inpatient
service (C-section, NICU, trauma, emergency, burn, cardiac surgery) → at most Moderate. A positive claim contradicted by a
negative one → at most Moderate. The same sentence copied into two columns counts once.

Only Strong and Moderate are recommended; Weak is shown as "mentioned, unverified".

## Results on all 10,088 facilities

| Service | Strong | Moderate | Weak | None |
| --- | ---: | ---: | ---: | ---: |
| Dialysis | 602 | 436 | 1,510 | 7,540 |
| Emergency C-section | 126 | 315 | 4,714 | 4,933 |
| NICU | 279 | 431 | 1,043 | 8,335 |
| Trauma care | 626 | 721 | 4,175 | 4,566 |
| 24x7 emergency | 1,297 | 1,528 | 2,127 | 5,136 |
| Burn care | 38 | 148 | 1,756 | 8,146 |
| Cardiac surgery | 277 | 326 | 3,381 | 6,104 |
| MRI | 604 | 324 | 3,683 | 5,477 |
| CT scan | 958 | 505 | 3,122 | 5,503 |

Reading it: C-section's large Weak count is mostly hospitals that list obstetrics but never name caesarean delivery;
burn care is genuinely rare (38 Strong nationwide), so many locations will honestly have no strong option.

## Calibration changes made after reviewing samples

| Problem seen in real samples | Fix |
| --- | --- |
| "Gastric bypass surgery" matched cardiac surgery | only `coronary artery bypass` / `CABG` count |
| "burnout", "Sun Burn Treatment" matched burn care | excluded contexts |
| "Nasal trauma surgery", "dental trauma" matched trauma care | excluded contexts |
| "dialysis unit with **no** waiting time" read as negative (teammate's earlier heuristic) | negation must be adjacent to the term |
| "cardiothoracic surgery up to **closed** heart" read as negative | `closed` only counts as "closed down / permanently" |
| identical sentence in `equipment` and `capability` counted as corroboration | dedupe sentences before counting |
| department lists counted as specific claims | new `listed` kind, cannot make a facility Strong alone |
| "MRI (via tie-up)", "outsourced" counted as in-house | new `indirect` kind → Weak |

Known limits: English-only regexes; claims may describe a different facility when a record was merged
(handled later by identity checks); a claim is evidence that a web page said it, not that the service runs today.
