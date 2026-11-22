# Impact: where the referral network has the largest gaps (2026-11-21)

CareMatch answers a patient's question: *where should I go for this service, from here?* This analysis answers the
planner's version: **which districts are far from any facility with credible evidence for a service, and do those
districts also show high need?** It uses all three challenge tables: facilities (evidence), the India Post PIN
directory (where people live), and NFHS-5 (need).

Reproduce: `python -m scripts.access_gaps` (32 s on a laptop). Outputs in [`analysis/`](../analysis/).
Code: [`carematch/planner.py`](../carematch/planner.py).

## Method

1. **Where people are.** 15,174 PIN areas with a reliable centre (post offices spread ≤ 60 km), grouped into 702 districts.
   Each area is weighted by its number of post offices, a rough stand-in for settlements.
2. **What counts as care.** A facility with **Strong or Moderate** evidence for the service, using exactly the rules the
   app uses for a patient (quoted claims, negation and referral handling, type and size caps). Duplicate listings count once.
3. **Distance.** Straight-line km from each PIN area to the nearest such facility. A district is an **access gap** when
   at least half of its post offices are more than 50 km away.
4. **Need (NFHS-5, 2019–21).** Caesarean-section rate and institutional births for maternal care; share of adults with
   raised blood sugar (> 140 mg/dl) for dialysis, since diabetes is the leading cause of kidney failure. The UN guidelines
   for monitoring emergency obstetric care (WHO/UNICEF/UNFPA) treat a population caesarean rate **below 5%** as a sign that
   women who need the operation cannot get it.
5. **Why the gap exists.** If fewer than 3 hospitals of any kind are listed within 50 km of the district centre, the gap
   is most likely in the **data** (the dataset barely covers the area). Otherwise it is a **service** gap: hospitals are
   listed nearby, but none documents this service.

NFHS is used only here, at district level. It never changes a facility's ranking for a patient.

## Findings

**1. Documented access is thin outside cities.** Share of India's post offices within each straight-line distance of a
facility with credible evidence:

| Service | ≤ 25 km | ≤ 50 km | ≤ 100 km | Access-gap districts (of 702) |
| --- | ---: | ---: | ---: | ---: |
| 24x7 emergency | 52% | 84% | 99% | 123 |
| CT scan | 38% | 70% | 95% | 214 |
| Trauma care | 36% | 67% | 91% | 269 |
| Dialysis | 35% | 65% | 91% | 268 |
| NICU | 30% | 59% | 90% | 308 |
| MRI | 29% | 58% | 90% | 308 |
| Cardiac surgery | 24% | 49% | 82% | 380 |
| **C-section** | **21%** | **46%** | **80%** | **405** |
| Burn care | 15% | 33% | 67% | 477 |

C-section is the starkest of the time-critical services: for more than half of the country's post offices, the nearest
facility that documents caesarean delivery is over 50 km away in a straight line.

**2. 27 districts are both far from C-section care and show unmet need.** All have most post offices > 50 km from
documented C-section care **and** an NFHS caesarean rate below 5%. They cluster in the **northeast** (Nagaland 8,
Meghalaya 5, Mizoram 2, Arunachal 1) and in **Rajasthan, Uttar Pradesh, Madhya Pradesh** (3, 3, 2).

| District | Median km to documented C-section | NFHS C-section rate | NFHS institutional births | Gap |
| --- | ---: | ---: | ---: | --- |
| Mon, Nagaland | 86 | 1.4% | 21.4% | data |
| Tuensang, Nagaland | 138 | 1.5% | 34.8% | data |
| Phek, Nagaland | 204 | 1.7% | 32.2% | data |
| Kiphire, Nagaland | 178 | 2.1% | 34.8% | data |
| Peren, Nagaland | 198 | 2.4% | 43.5% | data |
| South West Garo Hills, Meghalaya | 184 | 2.4% | 83.7% | data |
| Karauli, Rajasthan | 72 | 2.8% | 97.6% | data |
| Shravasti, Uttar Pradesh | 85 | 3.2% | 80.4% | data |
| Mamit, Mizoram | 134 | 3.5% | 75.0% | data |
| Kondagaon, Chhattisgarh | 190 | 3.6% | 78.7% | data |

Full list: [`analysis/priority_maternal.csv`](../analysis/priority_maternal.csv).

Two different problems hide in this list. In **Mon** only one birth in five happens in a facility: women do not reach
care at all. In **Karauli** (97.6% institutional births, 2.8% caesarean) women do reach facilities, but those facilities
rarely operate: the gap is surgical capacity, not access to a building.

**3. Most gaps are partly data gaps.** For 21 of the 27 maternal priorities, fewer than 3 hospitals of any kind are
listed within 50 km. The dataset is 88% private facilities and 5% public, so district hospitals and First Referral Units
that do perform caesareans are probably missing. Six districts are **service gaps**: hospitals are listed nearby, but none
documents caesarean delivery: Mokokchung (Nagaland), East Garo Hills and South West Khasi Hills (Meghalaya),
Alirajpur (Madhya Pradesh), Sahebganj (Jharkhand), Barmer (Rajasthan).

**4. Dialysis gaps overlap with high diabetes.** 36 districts are in the top quarter for raised blood sugar and have most
post offices > 50 km from documented dialysis, 20 of them service gaps. Examples: Prakasam, Andhra Pradesh (26.7% of
adults with raised blood sugar, median 127 km to documented dialysis), Ganjam, Odisha (18.6%, 135 km), Karimnagar,
Telangana (18.4%, 91 km, 8 hospitals listed nearby but none documents dialysis).
Full list: [`analysis/priority_dialysis.csv`](../analysis/priority_dialysis.csv).

## Actionable insights: recommended actions

| # | Action | Where | Why this, here |
| --- | --- | --- | --- |
| 1 | **Fix the data before building.** Add public facilities (district hospitals, CHCs/FRUs, national dialysis programme centres) to the facility list, with their documented services. | The 21 maternal and 16 dialysis "data gap" districts | The gap may be in the listing, not on the ground. Once these are in, CareMatch shows them to health workers with no code change. |
| 2 | **Verify, then upgrade, surgical obstetric capacity.** Confirm by phone which listed hospitals can do an emergency caesarean (CareMatch already prints the questions to ask); where none can, prioritise the district hospital for CEmONC staffing (obstetrician, anaesthetist, blood storage). | The 6 maternal "service gap" districts; districts like Karauli where births are in facilities but caesareans are rare | High institutional births with a very low caesarean rate points to missing surgical capacity, not missing buildings. |
| 3 | **Pre-arranged referral routes and transport.** For each priority district, name the nearest facility with credible evidence (CareMatch's top result from the district centre) and agree a referral and ambulance (108/102) protocol with it. | Northeast priority districts (Nagaland, Meghalaya, Mizoram), where the nearest documented C-section care is 85–200 km away | When the nearest capable facility is hours away, a known destination and transport plan saves the most time. |
| 4 | **Site the next dialysis units by need × distance.** Use the dialysis priority list (high blood sugar, far from documented dialysis) to choose where new units, or verification of existing ones, go first. | The 20 dialysis "service gap" districts, starting with Prakasam, Ganjam, Karimnagar | Kidney failure from diabetes needs dialysis 2–3 times a week; distance decides whether patients keep up. |

## Limits

- **Documented, not actual, capacity.** "No credible facility" means the public web listings in this dataset do not
  document the service. The dataset under-represents public facilities, so every gap is a lead to verify, not proof.
- **Straight-line distance.** Road distance, especially in hill districts, is longer; the real gaps there are larger.
- **Post offices approximate population.** They follow settlements, not head counts.
- **NFHS-5 is 2019–21 and uses older district boundaries.** 572 of 702 districts matched (537 by exact name, 35 by close
  spelling); most unmatched ones were created after the survey (for example Andhra Pradesh's 2022 districts).
  Values in parentheses in NFHS (25–49 cases) are kept and flagged `*_small_sample` in the CSV.
- **Association, not cause.** A low caesarean rate next to a long distance is consistent with an access problem; it does
  not prove distance is the cause.
