# CareMatch

**Find the right care in India, and know why to trust the answer.**

A community health worker has a patient who needs dialysis, an emergency caesarean or a newborn ICU. CareMatch takes a
**service** and a **place** (city, district, 6-digit PIN code or coordinates) and returns up to three facilities from the
Virtue Foundation dataset of 10,088 Indian facilities. Every suggestion quotes the facility text it rests on, says how
strong that evidence is and how far away the facility is, lists what is still uncertain, and gives the questions to ask
by phone. When the records do not support a recommendation, CareMatch says so instead of padding the list.

For planners it answers the next questions: **which districts are far from any facility with credible evidence, do
those districts also show high need, and if we can only make ten phone calls this week, whom should we call first?**

Built for the CMU × Databricks Datathon (Fall 2026) on Databricks Free Edition.

| Deliverable | Where |
| --- | --- |
| Single-file notebook (code, analysis, results) | [`CareMatch.ipynb`](CareMatch.ipynb): run all on Databricks or locally |
| App for health workers | Databricks App (Streamlit) in [`app/`](app/), deployed on Free Edition; see [`docs/deploy.md`](docs/deploy.md) |
| How it works | [`docs/system_design.md`](docs/system_design.md), [`docs/design.md`](docs/design.md), [`docs/evidence_calibration.md`](docs/evidence_calibration.md), [`docs/sort_modes_contract.md`](docs/sort_modes_contract.md) |
| Does it work | [`docs/evaluation.md`](docs/evaluation.md) |
| Actionable insights for planners | [`docs/impact.md`](docs/impact.md), [`docs/call_plan.md`](docs/call_plan.md), [`docs/lead_model.md`](docs/lead_model.md) |

## Why this is hard

The records were extracted automatically from web pages, so every field is a claim, not a fact:

- **A claim is not a service.** "MRI facility (outsourced)", "Caesarean section facility not available on-site" and a
  department list that happens to mention nephrology all contain the right words.
- **Locations contradict each other.** 434 records have coordinates that disagree with both their PIN code and their city.
- **Some records merge two facilities.** 12% of records contain statements about another branch or city.
- **Coverage is uneven.** 88% of facilities are private and 5% public; rural districts are thinly covered.

## How CareMatch decides

1. **Read each claim on its own.** Every item of the `procedure`, `equipment` and `capability` lists (and each
   description sentence) is classified as *direct*, *listed* (inside a department list), *indirect* (referral,
   outsourced, planned), *negative*, *mention* or *related* (a department, not the service).
2. **Turn claims into an evidence tier** per facility and service: **Strong** (two or more distinct direct claims in
   different columns, or with a related department), **Moderate** (one direct or listed claim), **Weak** (only indirect,
   passing or related evidence). Dentists, pharmacies and single-doctor listings are capped at Weak; small clinics
   claiming inpatient services and contradicted claims at Moderate. Only Strong and Moderate are ever recommended.
3. **Judge each location** by comparing the record's coordinates, its PIN code centre and its city centre. When two
   agree and one does not, the odd one out is treated as the error; unresolved conflicts lower the tier.
4. **Rank by distance bands, then evidence.** Take the nearest band (25 / 75 / 150 / 300 km) that contains any
   credible facility; inside it, stronger evidence first, then shorter straight-line distance. If only Moderate options
   are near and a Strong one is in the next band, show it as "farther, but stronger evidence". If nothing credible is
   within 300 km, say so.
5. **Explain and check every answer.** Each card cites quotes with their column, states what the evidence can and
   cannot show (a C-section record does not prove a surgeon is on duty tonight), lists uncertainties, and suggests the
   next step. Eight automatic checks run on every answer, including **citation fidelity**: every quote must appear word
   for word in the facility record.

The patient ranking trains no model and uses no LLM to score or explain: the rules fit on one page, give the same
answer every time, and cannot invent a citation. We chose distance bands over a weighted score because a single number
hides the trade-off between "near" and "well evidenced"; bands make it explicit.

**Why not always the closest, or always the best?** Always sending a patient to the closest facility is actionable but
not impactful: it ignores whether that facility can actually provide the service. Always sending them to the best
documented facility is impactful but often not actionable: it may be too far or unaffordable. CareMatch's default
balances the two: credible evidence within the nearest reachable radius, with options for urgency, cost and price. (A separate statistical model, below,
only suggests which facilities planners should phone to verify; it never changes what a patient is shown.)

## The app

- **Find care**: a search box, then a numbered list next to a map whose pins carry the same numbers. Three orders:
  **Best evidence** (the ranking above, with optional urgency and cost preferences), **Nearest** (straight-line, among
  credible branches whose location is certain), and **Compare listed prices** (within an extra distance you choose).
  Prices are shown exactly as quoted (exact, range, "up to", "from", free) with unit and conditions; quotes without a
  unit or with mismatched eligibility or inclusions are kept out of the comparison, insurer limits and equipment costs are labelled "not a patient price", and
  a public operator is never described as free. Prices are rarely documented, so this order usually falls back to
  distance and says so. A side-by-side note shows when the three orders pick different facilities.
- **Describe the situation** (optional): plain words such as "bleeding after delivery" or "road accident, head injury"
  (common English and romanized Hindi phrases; Hindi spellings unreviewed) suggest the service. The user chooses any travel preference. Danger
  signs show "call 108 / 102" first. Nothing is searched until the user checks the form and presses Find care; an
  ambiguous description only offers switches, and it is never a diagnosis.
- **Directions** open Google Maps (driving, driving that tries to avoid tolls, or walking) for reliably located
  branches only; the link carries the destination and nothing about the patient or where they are.
- **Planner pages**: a verification map (which PIN areas gain C-section coverage if the first 3, 5 or 10 calls succeed),
  service-verification leads with their model reasons and cited text, and travel-time scenarios under stated assumptions.

## Results

On a golden set of 38 queries (nine services; metros, tier-2 cities, rural PIN codes, remote and northeast districts):

| Check | Result |
| --- | --- |
| All quality checks pass (8 per answer on this set; up to 10 when prices or sort orders apply) | 38 / 38 queries |
| Quotes found word for word in the source column | 249 / 249 |
| Duplicate facility in a top 3 | 0 |
| Honest "nothing credible within 300 km" | 2 (Port Blair) |
| Median distance to the top recommendation | 1–3 km in cities, ~115 km in rural and remote places |
| Same top-1 when distance bands change (20/60/120/250 or 30/90/180/350 km) | 95% / 97% |

Every top-1 quote was judged by two independent model reviewers; a team member adjudicated all disagreements plus a
random sample of agreements. No reviewer found a quote that contradicts the service.

**Planner view** (all three tables: facilities, India Post PIN directory, NFHS-5): documented C-section care is within
50 km of only 46% of India's post offices. 27 districts are both far from it and have an NFHS caesarean rate below 5%,
mostly in the northeast; 21 of them are partly data gaps (few listings of any kind), which is itself an actionable
insight: fix the data before building.
Details and four actionable insights: [`docs/impact.md`](docs/impact.md).

**Whom to call first.** For C-section within 50 km, 7,402 of 14,008 reliably located PIN areas already have a facility
with credible evidence. Choosing calls greedily (each one adds the most still-uncovered PINs) would add **365 PINs with 3
calls** if the facilities confirm the service, against 152 for the three candidates with the largest individual reach
(they overlap); if the first call fails, the next two still add 258. A separate positive-unlabeled model, trained without
any C-section or maternity wording and tested on whole regions it never saw, ranks proxy positives with ROC-AUC 0.839 /
PR-AUC 0.053 (base rate 0.0125) against 0.757 / 0.031 for a simple rule, which is better at the very top of the list.
Details: [`docs/call_plan.md`](docs/call_plan.md), [`docs/lead_model.md`](docs/lead_model.md).

## Run it

**On Databricks Free Edition.** Import [`CareMatch.ipynb`](CareMatch.ipynb) and *Run all* on serverless compute; it reads
the three challenge tables from Unity Catalog through Spark (about 2–3 minutes on serverless). To deploy the app, follow
[`docs/deploy.md`](docs/deploy.md).

**Locally** (Python 3.10+, standard library only for the engine). Export the tables with
[`notebooks/00_export_data.py`](notebooks/00_export_data.py) into `data/`, then:

```bash
python -m unittest discover -s tests
```

```bash
python -m scripts.ask "dialysis|Patna" "C-section|Aurangabad, Bihar" "NICU|845401"
```

```bash
streamlit run app/app.py
```

```bash
python -m scripts.run_eval
```

```bash
python -m scripts.access_gaps
```

```bash
python -m scripts.call_plan --service c_section --radius 50 --budget 10
```

```bash
python -m scripts.lead_model
```

```bash
python -m scripts.build_notebook --execute
```

The last command regenerates the single-file notebook from the package source, so the notebook, the app and the tests
always run the same code.

## Repository

```text
carematch/      engine: textutil, services, evidence, geo, price, decision, review, recommend, strategy_compare,
                render, datasource; planner tools: planner, calls, call_map, lead_model, travel_scenario
app/            Databricks App (Streamlit), UI only; app/pages/ for the planner pages
notebooks/      00_export_data (snapshot tables), 02_demo (widgets)
scripts/        evaluation, access-gap analysis, call plan, lead model, notebook builder, CLI
eval/           golden queries, results, review sheet, strategy comparisons
analysis/       district access gaps, priority lists, call plan, PIN coverage, verification leads
docs/           design, calibration, evaluation, impact, deployment
tests/          unit and invariant tests
```

The dataset is not committed (`data/` is git-ignored).

## Limits

- A listing is evidence that a web page made a claim, not proof that the service runs today; the app says so on every
  card and turns the uncertainty into questions to ask by phone.
- Distances are straight-line, not road travel time.
- Patient prices are rarely documented; a price is a web quote to confirm by phone.
- Verification leads and coverage gains are planning estimates: they assume a facility confirms the service.
- Public facilities are under-represented, so rural gaps are partly gaps in the data.
- Claim rules are English-only and calibrated on this table.

## Credits

Parsing helpers in `carematch/textutil.py` are adapted from Charlie's search MVP
(`Sa1kyo121/carematch-india`, branch `feature/search`). Data: Virtue Foundation facility dataset, India Post PIN
directory and NFHS-5 district indicators, as provided for the challenge.

[Recording guide with the Delhi and three-call scenarios](docs/video_demo.md)
