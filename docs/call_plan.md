# Verification call plan: C-section, 50 km, 10 calls (2026-11-21)

**Question (district NGO coordinator):** *If I can make only 10 calls this week, which facilities should I verify
first, and which PIN areas that currently lack a credible referral option gain one for each confirmed facility?*

Reproduce: `python -m scripts.call_plan --service c_section --radius 50 --budget 10` (12 s).
Code: [`carematch/calls.py`](../carematch/calls.py). Outputs in [`analysis/`](../analysis/) (`c_section_*`).

## Definitions

| Term | Definition |
| --- | --- |
| PIN universe | unique 6-digit PIN codes with a reliable centre: the centre of the PIN's largest district entry, the same point the app uses when a user types that PIN. **14,008 of 19,586 PINs**; 5,578 excluded (post offices spread over > 60 km, or mis-geocoded to a same-name place in another state). A PIN that spans several districts is counted once. |
| Covered now | at least one facility with **Strong or Moderate** C-section evidence within **50 km** straight-line. A facility whose position is uncertain covers a PIN only if every candidate position is within range (the same conservative distance the app uses). Duplicate listings count once. |
| Candidate | C-section evidence still unverified (tier **Weak**) **and** obstetric or surgical leads in the record (obstetric text, or an obstetric specialty plus operating theatre / anaesthesia / blood bank / ICU), a hospital or ≥ 20 beds, not a specialist centre (ayurveda, dental, eye …) or nursing school. Moderate facilities are not candidates: verifying them raises confidence but adds no coverage under this metric. |
| Data check list | candidates held back because the record cannot be pinned to one branch: address, PIN and map position disagree; the record mixes facilities; or the branch name / listed city is > 50 km from the mapped position. |
| Needs contact | candidate without a phone number; listed, but not counted against the call budget. |
| Gain | newly covered **unique PINs**, *assuming the facility confirms it provides the service*. |

## Starting point

| | |
| --- | ---: |
| PINs (denominator) | 14,008 |
| Facilities with credible C-section evidence | 439 |
| PINs covered now | 7,402 (52.8%) |
| PINs without a credible option within 50 km | 6,606 |
| Candidates | 2,018 (821 would add coverage; 40 need contact details) |
| Held for data checks | 767 |

## Greedy plan (each call: the facility that adds the most still-uncovered PINs)

| Rank | Facility | State | Top lead (column) | New PINs | Cumulative |
| ---: | --- | --- | --- | ---: | ---: |
| 1 | SH Medical Centre, Kottayam | Kerala | "Obstetrics and Gynecology department" (capability); also "Performs obstetric and gynecologic surgical procedures." (procedure) | 150 | 150 |
| 2 | SanthaRam Hospital, Rajahmundry | Andhra Pradesh | "Blood Bank operates 24/7." (capability) + obstetrics specialty | 110 | 260 |
| 3 | Anu Specialty Hospital, Thanjavur | Tamil Nadu | "Departments include … Obstetrics & Gynaecology …" (capability) | 105 | 365 |
| 4 | Cauvery Heart & Multi-Speciality Hospital, Mysore | Karnataka | "Has performed 5,000 deliveries" (capability) | 100 | 465 |
| 5 | Dr. TMA Pai Hospital, Udupi | Karnataka | "Gynaecology outpatient department (OPD)" (capability) | 89 | 554 |
| 10 | Baby's Life Hospital, Hanamkonda | Telangana | "Obstetrician-Gynecologist (OBGYN) practice" (capability) | 67 | 936 |

Full table with PIN ids, phones and call questions: `analysis/c_section_call_plan.csv`. In post-office terms the ten
calls would add 4.9% of the reliable PINs' post offices (3 calls: 1.7%).

## Does the overlap-aware order matter?

Same candidates, radius and budgets; "top-K" picks the K facilities with the largest individual gain:

| Calls | Greedy (deduct overlap each round) | Top-K by individual gain | Upper bound* | Greedy / bound |
| ---: | ---: | ---: | ---: | ---: |
| 3 | **365** | 152 | 446 | 82% |
| 5 | **554** | 154 | 740 | 75% |
| 10 | **936** | 154 | 1,399 | 67% |

\* No set of K facilities can add more than the sum of the K largest individual gains, so this bounds every possible plan.

The ten largest individual gains all sit in central Kerala (Kottayam, Pathanamthitta), within 50 km of each other: calling
them in order would spend 10 calls to cover the same ~150 PINs. Deducting overlap sends calls 2–10 to six other states.
The bound is loose (it ignores overlap), so the true optimum is closer to the greedy figure than the ratio suggests.

## Where do those calls go? The need-targeted plan

Every call in the plan above lands in a state where caesareans are already common. Joining each PIN to its district's
NFHS-5 caesarean rate (10,740 of the 14,008 PINs have an NFHS match), the districts where the ten calls add coverage
have a **median caesarean rate of 47.8%**. More documented coverage there changes little.

So the same greedy rule is run again counting only **PINs in districts with a caesarean rate below 10%**
(`greedy_plan(..., target=...)`). WHO's 2015 statement on caesarean section rates finds that, at population level, rates
up to about 10% are associated with fewer maternal and newborn deaths; below that, access to the operation is plausibly
the constraint. 1,142 PINs are in such districts and 825 of them have no documented C-section care within 50 km.
Districts without an NFHS match are never assumed to have high need.

| Rank | Facility | State | Districts gaining coverage | District caesarean rate | New low-caesarean PINs | Cumulative |
| ---: | --- | --- | --- | ---: | ---: | ---: |
| 1 | Darbhanga Medical College, Laheriasarai | Bihar | Samastipur, Sitamarhi | 6.2% | 38 | 38 |
| 2 | Katihar Medical College and Hospital | Bihar | Katihar, Purnia, Araria | 4.0% | 24 | 62 |
| 3 | Jyothi Hospital, Kuruda | Odisha | Mayurbhanj | 8.6% | 24 | 86 |
| 4 | GBH American Hospital, Udaipur | Rajasthan | Udaipur, Rajsamand | 7.3% | 21 | 107 |
| 5 | Karimganj Civil Hospital | Assam | Karimganj, West Jaintia Hills | 7.0% | 21 | 128 |
| 10 | Krishna Hospital, Bhilwara | Rajasthan | Bhilwara | 5.9% | 12 | 205 |

| Calls | PIN-count plan: all PINs | of which low-caesarean | Need plan: low-caesarean PINs | Need plan: all PINs |
| ---: | ---: | ---: | ---: | ---: |
| 3 | 365 | **0** | **86** | 135 |
| 5 | 554 | **0** | **128** | 218 |
| 10 | 936 | **20** | **205** | 326 |

The need plan adds fewer PINs in total, because low-caesarean districts are larger and less densely divided into PINs.
That is the point: a PIN count measures how finely an area is divided, and need is in the places it under-counts.
The first lead is a government medical college whose scraped record only mentions a blood bank and operation theatres:
a single phone call would very likely confirm it, which is exactly the kind of gap a verification call is for.
Full table: `analysis/c_section_call_plan_need.csv`; the verification map in the app switches between the two objectives.

## If the first facility says no

Remove it and re-plan: Sanjeevani Hospital (Kottayam, +148) takes rank 1, then the same SanthaRam and Anu hospitals;
three calls still add 363 PINs. `analysis/c_section_call_plan_if_first_fails.csv`.

## For the map

`analysis/c_section_pin_status.csv`: one row per PIN with `covered_now`, nearest credible facility (km, tier, id) and
`newly_covered_at_rank`. The number of PINs with `newly_covered_at_rank ≤ 3` equals row 3 `cumulative_gain` (365).

## Limits

- **Every gain assumes the call confirms the service.** A candidate is a lead from public text, not evidence of service.
- **PIN counts favour dense areas.** Kerala has many small PINs, so a 50 km circle there holds ~150 PINs; post-office
  weighted shares are reported alongside (`cumulative_share_of_post_offices`). Neither is a head count. The need-targeted
  plan above is our answer to this limit.
- **A district caesarean rate is a proxy for need.** It mixes access with preference and private-sector practice, NFHS-5
  is from 2019–21, and 3,268 PINs sit in districts without an NFHS match and are left out of the target.
- **Straight-line 50 km** understates travel in hill districts.
- **Greedy is not guaranteed optimal**; it is within (1 − 1/e) ≈ 63% of the optimum by theory and at least 67–82% of a
  loose upper bound here.
