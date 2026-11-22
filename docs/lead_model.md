# C-section verification leads: a positive-unlabeled model (2026-11-21)

**Question.** Which facilities look like the ones that document caesarean delivery, but do not document it themselves?
Those are the facilities a district planner should verify first. The model ranks facilities for **verification calls
only**. A high score is never evidence that a facility offers C-section, and leads never enter patient recommendations.

Reproduce: `python -m scripts.lead_model` (about 30 s). Code: [`carematch/lead_model.py`](../carematch/lead_model.py),
tests: [`tests/test_lead_model.py`](../tests/test_lead_model.py). Outputs in [`analysis/`](../analysis/):
`c_section_lead_model_metrics.json`, `c_section_lead_model_coefficients.csv`, `c_section_leads.csv`.

## Setup

| | |
| --- | --- |
| Proxy positives | Facilities whose records give **Strong** C-section evidence (the engine's tier) |
| Unlabeled | Every other record (Moderate, Weak, no evidence). Many of them may offer the service without saying so; that is why this is positive-unlabeled learning, not classification |
| Model | Standardized logistic regression, balanced class weights, C = 0.3 (fixed before evaluation) |
| Validation | Leave-one-region-out over six regions of India; every facility group stays in one fold |
| Leads | Out-of-fold scores: each facility is scored by a model that never saw its region or its group |

### Features (42), and what is deliberately excluded

- **Kept:** facility type and operator; beds, doctors and founding year (log, with missing flags); phone, website, number
  of source pages, social-media followers; counts of specialties in ten families (surgical, medical, emergency/critical
  care, paediatric, diagnostic, general medicine, dental, eye, traditional medicine, other); counts of procedure,
  equipment and capability items and description length; and 13 generic capability signals (ICU, operation theatre,
  ventilator, round-the-clock service, ambulance, CT/MRI, ultrasound, laparoscopy/endoscopy, dialysis, laboratory,
  inpatient beds, insurance, surgery).
- **No service vocabulary.** Every claim fragment, description sentence and specialty matching the exclusion pattern is
  removed **before** any feature is computed: caesarean, C-section, LSCS, CEmONC, obstetric, gynaecology, maternity,
  delivery, labour room, pregnancy, natal/neonatal, NICU/SNCU, perinatal, fetal, fertility/IVF, midwife, birth,
  anaesthesia, blood bank, women, mother. This covers the label's own direct and related vocabulary and its maternal
  neighbours. The test `test_adding_service_text_changes_nothing` adds such text to every field of a record and checks
  that the features and citations do not change at all.
- **Nothing label-derived.** No evidence tier, claim kind or count of service claims is a feature, and item counts only
  count fragments that survived the exclusion (a Strong record's C-section claims cannot inflate its procedure count).

### Leakage controls

- **Facility groups.** Engine duplicates (same name and same PIN or within 2 km) are joined with records sharing a
  normalized name (branches of a chain): 9,572 groups, 333 with several records. A group is assigned to its members'
  majority region, which moved 298 records out of their own state's region, so a group never straddles folds.
- **Geographic hold-out.** Regions: North, West, Central, East, Northeast, South (plus 101 records with an unknown
  state, held out as their own fold).
- **Label shuffle.** Re-running the whole pipeline with shuffled labels gives chance-level scores (below).

## Sample sizes

| Region (held out) | Facilities | Groups | Proxy positives |
| --- | ---: | ---: | ---: |
| North | 2,981 | 2,773 | 45 |
| West | 2,714 | 2,565 | 39 |
| South | 2,679 | 2,570 | 24 |
| East | 1,020 | 986 | 11 |
| Central | 432 | 416 | 6 |
| Northeast | 161 | 161 | 1 |
| Unknown state | 101 | 101 | 0 |
| **All** | **10,088** | **9,572** | **126** (1.25%) |

Unlabeled: 9,962 (313 Moderate, 4,716 Weak, 4,933 no evidence).

## Results (all held out by region)

| Ranking | ROC-AUC | PR-AUC | Precision@50 | Precision@100 | Precision@200 |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Model** | **0.839** | **0.053** | 0.04 | 0.05 | 0.075 |
| Baseline: hospitals first, then more listed specialties | 0.757 | 0.031 | 0.10 | 0.05 | 0.025 |
| Random | 0.500 | 0.0125 | 0.0125 | 0.0125 | 0.0125 |
| Model with shuffled labels (5 runs) | 0.506 (0.46–0.56) | 0.014 | | | |

By region (model / baseline ROC-AUC; PR-AUC in brackets). AUC is not reported for folds with fewer than 5 positives
(Northeast has 1, Unknown 0):

| Region | Model | Baseline |
| --- | --- | --- |
| North | 0.850 (0.073) | 0.775 (0.046) |
| West | 0.855 (0.057) | 0.708 (0.051) |
| South | 0.817 (0.064) | 0.757 (0.020) |
| East | 0.789 (0.041) | **0.881 (0.046)** |
| Central | 0.748 (0.033) | 0.675 (0.024) |

**Check on records the model was not trained to find.** Moderate records do document C-section (one direct or listed
claim) but were unlabeled in training. If the model has learned something real, it should rank them above records with
no C-section evidence at all. It does: ROC-AUC **0.861**, PR-AUC **0.444** against a prevalence of 0.060
(baseline 0.822 / 0.345).

**Regularization.** C from 0.03 to 3 changes ROC-AUC by at most 0.002 and PR-AUC not at all.

### Reading the results honestly

- The model ranks facilities well overall (ROC-AUC 0.84 on regions it never saw, versus 0.76 for the rule), and its
  PR-AUC is about 4 times the base rate. The label-shuffle control shows this is not leakage.
- **PR-AUC stays low in absolute terms** (0.05). With 126 proxy positives among 10,088 records, and many unlabeled
  records that probably do offer the service, a precise list cannot be expected. These are leads, not answers.
- **The simple rule finds more Strong records in its very top 50** (5 vs 2). The two tie at rank 100, and by rank 200
  the model has found three times as many (15 vs 5). The model wins in four of five regions; the East is the exception.
- **What the model learns is mostly "a well-documented general hospital"**. Largest positive weights: listed as a
  hospital (+1.78), more procedure items (+0.86), laparoscopy or endoscopy (+0.53), diagnostic specialties (+0.37),
  more source pages (+0.30), paediatric specialties (+0.28), public operator (+0.26). Largest negative: clinic (−1.48)
  or other type (−0.66), more capability items (−0.52), traditional medicine (−0.38), more surgical specialties (−0.37),
  longer description (−0.36). That matches the proxy: Strong evidence needs a facility that publishes detailed
  procedure lists. A hospital that fits this profile but never mentions caesarean delivery is exactly the kind of
  record worth a phone call.
- **Do not read single weights causally.** Features are correlated, so each weight is conditional on the others; for
  example, mentioning an operation theatre gets a small negative weight (−0.20) once hospital type and procedure counts
  are in the model. Full table: `analysis/c_section_lead_model_coefficients.csv`.
- An exploratory variant with 58 individual specialty flags scored similarly (ROC-AUC 0.84) but gave unstable,
  hard-to-explain weights (some dental specialties weighted positive), so the ten families were kept.

## Leads exported

`analysis/c_section_leads.csv`: the 200 highest-scoring facilities among those with **Weak or no** C-section evidence
(dentists, pharmacies and single-doctor listings excluded): 191 Weak, 9 none; 195 with a phone number; all with a
position. Each row has the held-out score and its percentile, up to four reasons (only features the record actually has,
each with its contribution), the **verbatim facility text** behind each reason, the current C-section evidence note
(context for the caller, not a model input), and the use note.

Example (rank 1):

> **Kevalya Hospital, Thane, Maharashtra** · score 0.991 · current C-section evidence: weak
> Reasons: listed as a hospital (+1.43) · number of source pages (+0.97) · mentions ventilators (+0.94) · mentions
> laparoscopy or endoscopy (+0.90)
> Cited: equipment: "8-bed ICU with ventilators and advanced cardiac and respiratory support" · procedure: "Laparoscopic surgeries"

105 of the 200 leads (28 of the top 50) are also in line A's rule-based call candidates, which were built from obstetric
and surgical wording the model never sees. The two methods reach many of the same facilities from different evidence.

## Limits

- **Strong is a proxy, not ground truth.** It marks facilities whose web text documents C-section in detail, so the model
  partly learns documentation habits (rich procedure lists, more source pages). It cannot tell an unadvertised maternity
  unit from a hospital that truly has none.
- **Scores are ranks, not probabilities.** With an unknown share of hidden positives among the unlabeled, the scores are
  not calibrated; use the order and the percentile.
- **Few positives per region** (6 in Central, 1 in the Northeast) make regional estimates noisy.
- **For planners only.** A lead is a reason to call, never a reason to refer. Nothing here changes what CareMatch
  recommends to a patient.
