"""Build the single-file submission notebook, CareMatch.ipynb, from the repo's source.

    python -m scripts.build_notebook              # write CareMatch.ipynb (no outputs)
    python -m scripts.build_notebook --execute    # also run every cell here on data/*.csv and save the outputs

Part 1 of the notebook is the carematch package itself, inlined module by module, so the notebook, the app and the
tests always run the same code. Relative imports are rewritten (a top-level `from .x import y` is dropped because
earlier cells already defined y; one inside a function becomes `y = globals()['y']`) and `__main__` blocks are removed.
Golden queries and review labels are embedded from eval/ so the file stands alone.
"""
import argparse
import ast
import contextlib
import csv
import io
import os
import subprocess
import sys
import time
import traceback

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook, new_output

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'CareMatch.ipynb')
REPO = 'https://github.com/DDaniel-code/carematch'

MODULES = [
    ('textutil', 'Parsing helpers: the dataset stores lists as JSON text; coordinates are checked against India; straight-line distance.'),
    ('services', 'The nine services: which phrases are direct evidence, which are only related departments, which contexts are false hits '
                 '("dental trauma"), negation and referral patterns, what each service\'s evidence can and cannot show, and what to ask by phone.'),
    ('evidence', 'Every claim (one item of a `procedure` / `equipment` / `capability` list, or one description sentence) is classified on its own: '
                 'direct, listed, indirect (referral, outsourced, planned), negative, mention, related. Claims become a tier: Strong, Moderate, '
                 'Weak or None, with caps for facility type, small clinics and contradictions. Also detects claims about another facility.'),
    ('geo', 'Turns the user\'s place (city, district, PIN, or "lat, lon") into a point with a stated precision, and judges each facility\'s '
            'position by comparing its coordinates, its PIN centre and its city centre.'),
    ('review', 'Eight automatic quality checks run on every answer, including citation fidelity: every quote must appear word for word in the '
               'named column of the facility record.'),
    ('recommend', 'The ranking: only Strong or Moderate evidence is recommended; take the nearest distance band (25/75/150/300 km) that has any; '
                  'inside it, stronger evidence first, then distance. Builds cards with quotes, uncertainties, phone, questions to ask, '
                  'runner-ups with the reason they lost, and an honest no-answer.'),
    ('render', 'Plain-text rendering of a result (used below and in the CLI).'),
    ('datasource', 'Loads the three tables from Spark (Databricks), a SQL warehouse (the app), a Volume snapshot or local CSVs, converting '
                   'every value to the same text so results are identical everywhere.'),
    ('planner', 'District access gaps for planners: distance from every PIN area to the nearest credible facility, joined with NFHS-5 need. '
                'Used only in Part 6; NFHS never affects a patient\'s ranking.'),
]

DEMO = [('Dialysis', 'Patna'), ('MRI scan', 'Darbhanga'), ('Burn care', 'Gaya'), ('Trauma care', 'Kohima'),
        ('Burn care', 'Port Blair')]


# ---- source inlining ------------------------------------------------------------------------------------------------

def inline_module(name):
    path = os.path.join(ROOT, 'carematch', f'{name}.py')
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    edits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            if node.col_offset == 0:
                repl = ''
            else:
                pad = ' ' * node.col_offset
                repl = ''.join(f"{pad}{a.asname or a.name} = globals()['{a.name}']\n" for a in node.names)
            edits.append((node.lineno - 1, node.end_lineno, repl))
    for node in tree.body:
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == '__name__'):
            edits.append((node.lineno - 1, node.end_lineno, ''))
    for start, end, repl in sorted(edits, reverse=True):
        lines[start:end] = [repl] if repl else []
    body = ''.join(lines).rstrip() + '\n'
    return f'# ===== carematch/{name}.py (inlined from the repo by scripts/build_notebook.py) =====\n' + body


def top_level_names(code):
    names = set()
    for node in ast.parse(code).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def git_sha():
    try:
        sha = subprocess.check_output(['git', '-C', ROOT, 'rev-parse', '--short', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', ROOT, 'status', '--porcelain', '--', 'carematch'], text=True).strip()
        return sha + (' + local changes to carematch/' if dirty else '')
    except Exception:
        return 'unknown'


def read_csv(path):
    csv.field_size_limit(sys.maxsize)
    with open(os.path.join(ROOT, path), newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


# ---- notebook content -----------------------------------------------------------------------------------------------

INTRO = """# CareMatch: find the right care in India, with the evidence behind every answer

**CMU × Databricks Datathon, Fall 2026** · Code: {repo} · Built from commit `{sha}`

A patient needs a specific kind of care. CareMatch takes a **service** (dialysis, C-section, NICU, trauma care, emergency
care, burn care, cardiac surgery, MRI, CT) and a **place** (city, district, PIN code or coordinates) and returns up to three
facilities from the Virtue Foundation dataset. Every recommendation quotes the facility text it rests on, says how strong
that evidence is and how far away the facility is, lists what is still uncertain, and gives the questions to ask by phone.
When the records do not support a recommendation, it says so instead of padding the list.

For planners it answers the next question: **which districts are far from any facility with credible evidence, and do
those districts also show high need** in NFHS-5?

| Judging criterion | Where in this notebook |
| --- | --- |
| Exploration | Part 3: what a record is, how far each field can be trusted, what the claims can and cannot prove |
| Modeling | Parts 1, 4, 5: claim classification, evidence tiers, location confidence, banded ranking, quality checks, evaluation, sensitivity |
| Impact | Part 6: district access gaps × NFHS need, and four recommended actions |

**How to run.** On Databricks Free Edition (serverless): import this file and *Run all*; Part 2 reads the three Unity
Catalog tables through Spark. Locally: put the exported CSVs in `data/` and run all cells. The outputs saved in this file
come from a local run on the full exported tables (`notebooks/00_export_data.py` in the repo); the same cells run
unchanged on Databricks, and Part 2 prints which source was used.

**How this file is made.** Part 1 is the repo's `carematch` package inlined module by module by
`scripts/build_notebook.py`, so this notebook, the Databricks App and the unit tests run the same code.
The same engine is deployed as a Databricks App (Streamlit) for health workers; see the video.
"""

SETUP = r'''import csv, json, math, os, re, statistics, sys, time
from collections import Counter

ON_DATABRICKS = 'spark' in globals()
print('Running on', 'Databricks (Spark)' if ON_DATABRICKS else 'local Python', sys.version.split()[0])


def show(rows, cols, headers=None, limit=None):
    """Print a list of dicts as an aligned text table."""
    headers = headers or cols
    rows = rows[:limit] if limit else rows
    cells = [[('' if r.get(c) is None else str(r.get(c))) for c in cols] for r in rows]
    widths = [max([len(h)] + [len(row[i]) for row in cells]) for i, h in enumerate(headers)]
    line = lambda vals: '  '.join(v.ljust(w) for v, w in zip(vals, widths))
    print(line(headers))
    print(line(['-' * w for w in widths]))
    for row in cells:
        print(line(row))
'''

PART1 = """## Part 1 · The engine

Pure Python, standard library only, {lines:,} lines. The modules below run in dependency order. No model is trained
and no LLM is involved: every rule is written down, tested, and calibrated on the full table
(`docs/evidence_calibration.md` in the repo), so the same input always gives the same answer and every answer can be
traced back to the text that produced it.
"""

PART2 = """## Part 2 · Load the data

Three tables from `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset`: `facilities`
(10,088 rows × 51 columns), `india_post_pincode_directory` (aggregated to one row per PIN × district) and
`nfhs_5_district_health_indicators` (706 districts). Then every facility is assessed once for all nine services.
"""

LOAD = r'''started = time.perf_counter()
if ON_DATABRICKS:
    facility_rows, pincode_rows, load_info = load(spark=spark)
    nfhs_rows = load_nfhs(spark=spark)
else:
    facility_rows, pincode_rows, load_info = load(order=['local'])
    nfhs_rows = load_nfhs()
index = CareIndex(facility_rows, pincode_rows)
for service in SERVICES:
    index.assessments(service)
print(load_info)
print(f'{len(nfhs_rows)} NFHS-5 districts')
print(f'Index built and all {len(SERVICES)} services assessed in {time.perf_counter() - started:.1f} s')
'''

PART3 = """## Part 3 · Exploration: how much can each record be trusted?

The records were extracted automatically from web pages (Practo, JustDial, Facebook, hospital sites). Three problems
shape everything that follows: **claims are not facts**, **locations contradict each other**, and **some records merge
two facilities**. The cells below measure each one on the full table.
"""

EXPLORE_FIELDS = r'''cols = ['name', 'facilityTypeId', 'operatorTypeId', 'specialties', 'procedure', 'equipment', 'capability',
        'description', 'phone_numbers', 'latitude', 'address_zipOrPostcode', 'source_urls', 'capacity', 'numberDoctors',
        'yearEstablished']
n = len(facility_rows)
show([{'column': c, 'filled': f"{sum(not is_empty(r.get(c)) for r in facility_rows) / n:.0%}"} for c in cols],
     ['column', 'filled'])
print()
types = Counter(normalize(r.get('facilityTypeId')) or '(empty)' for r in facility_rows)
operators = Counter(normalize(r.get('operatorTypeId')) or '(empty)' for r in facility_rows)
print('Facility type:', ', '.join(f'{k} {v:,}' for k, v in types.most_common(5)))
print('Operator:     ', ', '.join(f'{k} {v:,}' for k, v in operators.most_common(3)))
print('\nScale fields (beds, doctors) are filled for a minority of rows, so they can only cap a tier, never rank.')
'''

EXPLORE_LOCATION = r'''conf = Counter(loc['confidence'] for loc in index.locations)
basis = Counter(loc['basis'] or 'no usable position' for loc in index.locations)
flags = Counter(f for loc in index.locations for f in loc['flags'])
print('Location confidence:', dict(conf.most_common()))
print('\nPosition used for distance:')
for k, v in basis.most_common():
    print(f'  {v:6,}  {k}')
print('\nLocation flags:', dict(flags.most_common(6)))
'''

EXPLORE_IDENTITY = r'''groups = Counter(index.dup_group)
dup_groups = sum(1 for c in groups.values() if c > 1)
dup_rows = sum(c for c in groups.values() if c > 1)
mixed = sum(1 for m in index.mixing if m)
print(f'Duplicate listings: {dup_rows} rows in {dup_groups} groups (same name and same PIN or within 2 km); shown once, sources kept.')
print(f'Records that look merged with another facility: {mixed:,} of {len(facility_rows):,} ({mixed / len(facility_rows):.0%}).')
example = next((facility_rows[i].get('name'), m) for i, m in enumerate(index.mixing) if m)
print('Example:', example[0], '->', example[1][0] if isinstance(example[1], list) else example[1])
'''

EXPLORE_EVIDENCE = r'''rows = []
for key, spec in SERVICES.items():
    tiers = Counter(a['tier'] for a in index.assessments(key))
    rows.append({'service': spec['label'], 'strong': tiers['strong'], 'moderate': tiers['moderate'],
                 'weak': tiers['weak'], 'none': tiers['none']})
show(rows, ['service', 'strong', 'moderate', 'weak', 'none'])
print('\nOnly Strong and Moderate are ever recommended. Weak = only referral/outsourcing, a passing mention, or a related department.')

print('\nWhat each kind of claim looks like (real text):')
seen = {}
for key in ('c_section', 'mri', 'dialysis', 'cardiac_surgery'):
    for a in index.assessments(key):
        for e in a['evidence']:
            seen.setdefault(e['kind'], (SERVICES[key]['label'], e['field'], e['text']))
for kind in ('direct', 'listed', 'indirect', 'negative', 'mention', 'related'):
    if kind in seen:
        label, field, quote = seen[kind]
        print(f'  {kind:9s} [{label}, {field}] "{quote[:110]}"')
'''

PART4 = """## Part 4 · Recommendations

Five queries chosen to show the behaviours that matter: plenty of strong options (Patna), a trade-off between near and
better evidenced (Darbhanga), an honest long-distance answer (Gaya), a remote northeast district (Kohima), and an honest
"nothing credible within 300 km" (Port Blair). Each answer carries its own quality review.
"""

DEMO_CELL = r'''for service, place in DEMO:
    result = recommend(index, service, place)
    print('=' * 100)
    print(to_text(result))
    if 'review' in result:
        checks = result['review']['checks']
        print(f"Quality review: {sum(c['passed'] for c in checks)}/{len(checks)} checks passed")
    print()
'''

PART5 = """## Part 5 · Evaluation

**Golden set**: 38 queries covering the nine services in metros, tier-2 cities, rural PIN codes and remote or northeast
districts, including places where the honest answer is "nothing credible nearby". Automatic metrics are recomputed here;
the review labels come from the layered review in the repo (`eval/review_sheet.csv`): two independent model reviewers
judged every top-1 quote, and a team member adjudicated every disagreement plus a random sample of agreements.
"""

EVAL_RUN = r'''runs, latencies = [], []
for qid, service, place, place_type in GOLDEN:
    t = time.perf_counter()
    r = recommend(index, service, place)
    latencies.append((time.perf_counter() - t) * 1000)
    runs.append((qid, service, place, place_type, r))

errors = [q for q, *_, r in runs if 'error' in r]
answered = [x for x in runs if x[4].get('results')]
failed_checks = Counter(c['name'] for *_, r in runs for c in r.get('review', {}).get('checks', []) if not c['passed'])
quotes = sum(len(c['evidence']) for *_, r in runs for c in r.get('results', []))
dups = [q for q, *_, r in runs if len({c['facility_id'] for c in r.get('results', [])}) != len(r.get('results', []))]
tiers = Counter(c['tier'] for *_, r in runs for c in r.get('results', []))
lat = sorted(latencies)
print(f'Queries: {len(runs)}  errors: {len(errors)}  answered within 300 km: {len(answered)}  honest no-answer: {len(runs) - len(answered) - len(errors)}')
print(f'All 8 quality checks passed: {sum(1 for *_, r in runs if r.get("review", {}).get("passed"))}/{len(runs)}'
      + (f'  failures: {dict(failed_checks)}' if failed_checks else ''))
print(f'Quotes shown in recommendations: {quotes} (each verified verbatim against its source column by the review)')
print(f'Duplicate facility inside a top 3: {len(dups)}')
print(f'Recommendations: {sum(tiers.values())} ({tiers["strong"]} Strong, {tiers["moderate"]} Moderate)')
print(f'Latency with a warm index: p50 {lat[len(lat) // 2]:.0f} ms, p95 {lat[int(len(lat) * 0.95) - 1]:.0f} ms')

print('\nMedian straight-line distance to the top recommendation:')
by_type = {}
for qid, service, place, place_type, r in answered:
    by_type.setdefault(place_type, []).append(r['results'][0]['distance_km'])
show([{'place type': k, 'queries answered': len(v), 'median km': round(statistics.median(v), 1)} for k, v in by_type.items()],
     ['place type', 'queries answered', 'median km'])
'''

EVAL_SENSITIVITY = r'''def top_ids(r):
    return [c['facility_id'] for c in r.get('results', [])]

baseline = {q: top_ids(r) for q, *_, r in runs}
variants = {'distance bands 20/60/120/250 km': dict(bands=(20, 60, 120, 250)),
            'distance bands 30/90/180/350 km': dict(bands=(30, 90, 180, 350)),
            'Strong requires >= 3 distinct claims': dict(strong_min_claims=3)}
rows = []
for name, kw in variants.items():
    same_top1, jacc = 0, []
    for qid, service, place, place_type in GOLDEN:
        ids = top_ids(recommend(index, service, place, review=False, **kw))
        base = baseline[qid]
        same_top1 += (ids[:1] == base[:1])
        jacc.append(len(set(ids) & set(base)) / len(set(ids) | set(base)) if (ids or base) else 1.0)
    rows.append({'variant': name, 'same top-1': f'{same_top1 / len(GOLDEN):.0%}', 'top-3 overlap (Jaccard)': f'{statistics.mean(jacc):.2f}'})
show(rows, ['variant', 'same top-1', 'top-3 overlap (Jaccard)'])
print('\nThe answer barely depends on the exact distance cut-offs and more on how much evidence "Strong" demands,')
print('which is why the product shows tiers and the quotes themselves rather than a precise score.')
'''

EVAL_REVIEW = r'''def count(col):
    return dict(Counter(v[col] for v in REVIEW.values() if v[col]).most_common())

print(f'Top-1 answers reviewed: {len(REVIEW)}')
print('Quote supports the service   model A:', count('model_quote_supports'), '| model B:', count('xcheck_quote_supports'))
print('One real facility            model A:', count('model_one_facility'), '| model B:', count('xcheck_one_facility'))
agree = sum(1 for v in REVIEW.values() if v['models_agree'] == 'yes')
print(f'Models agree on both questions: {agree}/{len(REVIEW)}')
human = {k: v for k, v in REVIEW.items() if v['human_quote_supports']}
print(f'\nHuman adjudication ({len(human)} rows: every disagreement plus a random sample of agreements):')
for k, v in human.items():
    print(f"  {k} {v['service']:<16} {v['place']:<14} quote supports: {v['human_quote_supports']:<7} one facility: {v['human_one_facility']:<9} {v['human_note'][:70]}")
print('\nNo reviewer found a quote that contradicts the service. "Partly" means the quote proves the service is offered but')
print('not that it is available right now (e.g. emergency C-section readiness): the card states exactly that and says what to confirm by phone.')
'''

PART6 = """## Part 6 · Impact: where the referral network has the largest gaps

For every India Post PIN area with a reliable centre (15,174 areas, 702 districts, weighted by number of post offices as a
rough stand-in for settlements), we measure the straight-line distance to the nearest facility with **Strong or
Moderate** evidence for each service, using exactly the rules above. A district is an **access gap** when at least half of
its post offices are more than 50 km away. We then put NFHS-5 need next to it: the caesarean rate (UN emergency-obstetric-care
guidelines treat a population rate below 5% as unmet need) and institutional births for maternal care, and the share of
adults with raised blood sugar for dialysis. Where fewer than 3 hospitals of any kind are listed within 50 km, the gap is
most likely in the **data**; otherwise it is a **service** gap.
"""

GAPS_RUN = r'''started = time.perf_counter()
table, nfhs_match, national = district_table(index, list(SERVICES), nfhs_rows)
print(f'{len(table)} districts in {time.perf_counter() - started:.0f} s; NFHS matched: {nfhs_match}')
print('\nShare of post offices within each straight-line distance of a facility with credible evidence:')
rows = [{'service': SERVICES[s]['label'], '<=25 km': f"{v['within_25km']:.0%}", '<=50 km': f"{v['within_50km']:.0%}",
         '<=100 km': f"{v['within_100km']:.0%}", 'access-gap districts': f"{v['districts_with_access_gap']}/{v['districts']}"}
        for s, v in sorted(national.items(), key=lambda kv: -kv[1]['within_50km'])]
show(rows, ['service', '<=25 km', '<=50 km', '<=100 km', 'access-gap districts'])
'''

GAPS_PRIORITY = r'''maternal = maternal_priorities(table)
dialysis = dialysis_priorities(table)
for r in maternal + dialysis:
    r['gap'] = 'data' if gap_kind(r).startswith('data') else 'service'
for r in maternal:
    r['far'] = f"{r['c_section_share_far']:.0%}"
for r in dialysis:
    r['far'] = f"{r['dialysis_share_far']:.0%}"

print(f'MATERNAL PRIORITIES: {len(maternal)} districts far from documented C-section care with an NFHS caesarean rate below 5%')
show(maternal, ['district', 'state', 'c_section_median_km', 'far', 'csection_pct', 'institutional_birth_pct',
                'hospitals_listed_within_50km', 'gap'],
     ['district', 'state', 'median km', 'post offices >50 km', 'C-section %', 'inst. births %', 'hospitals <50 km', 'gap'], limit=15)
print(f'\nDIALYSIS PRIORITIES: {len(dialysis)} districts far from documented dialysis, top quarter for raised blood sugar')
show(dialysis, ['district', 'state', 'dialysis_median_km', 'far', '_sugar', 'hospitals_listed_within_50km', 'gap'],
     ['district', 'state', 'median km', 'post offices >50 km', 'raised sugar %', 'hospitals <50 km', 'gap'], limit=12)
'''

GAPS_FINDINGS = r'''cs = national['c_section']
by_state = Counter(r['state'] for r in maternal)
data_gaps = sum(r['gap'] == 'data' for r in maternal)
service_gaps = [r['district'] + ', ' + r['state'] for r in maternal if r['gap'] == 'service']
print(f"1. Documented C-section care is within 50 km of only {cs['within_50km']:.0%} of post offices; {cs['districts_with_access_gap']} of {cs['districts']} districts are access gaps.")
print(f"2. {len(maternal)} districts are both far from it and show unmet need; most are in " +
      ', '.join(f'{s} ({n})' for s, n in by_state.most_common(4)) + '.')
contrast = [r for r in maternal if r['institutional_birth_pct'] is not None]
low = min(contrast, key=lambda r: r['institutional_birth_pct'])
high = max(contrast, key=lambda r: r['institutional_birth_pct'])
print(f"3. Two different problems: in {low['district']} only {low['institutional_birth_pct']:.0f}% of births are in a facility (women do not reach care);")
print(f"   in {high['district']} {high['institutional_birth_pct']:.0f}% are, yet only {high['csection_pct']}% are caesareans (facilities that rarely operate).")
print(f"4. {data_gaps} of {len(maternal)} maternal priorities have fewer than 3 hospitals of any kind listed nearby: the dataset (88% private) probably misses")
print(f"   their public hospitals. Service gaps (hospitals listed, none documents C-section): {'; '.join(service_gaps) or 'none'}.")
print(f"5. {len(dialysis)} districts combine poor documented dialysis access with high raised-blood-sugar prevalence;"
      f" {sum(r['gap'] == 'service' for r in dialysis)} of them are service gaps.")
'''

ACTIONS = """### Recommended actions

| # | Action | Where | Why |
| --- | --- | --- | --- |
| 1 | **Fix the data before building.** Add public facilities (district hospitals, CHCs / First Referral Units, national dialysis programme centres) with their documented services. | The "data gap" districts above | The gap may be in the listing, not on the ground. Once added, CareMatch shows them to health workers with no code change. |
| 2 | **Verify, then upgrade, surgical obstetric capacity.** Confirm by phone which listed hospitals can do an emergency caesarean (CareMatch prints the questions); where none can, prioritise the district hospital for emergency obstetric staffing (obstetrician, anaesthetist, blood storage). | The maternal "service gap" districts, and districts where births happen in facilities but caesareans are rare | High institutional births with a very low caesarean rate points to missing surgical capacity, not missing buildings. |
| 3 | **Pre-arranged referral routes and transport.** Name the nearest facility with credible evidence for each priority district (CareMatch's answer from the district centre) and agree a referral and ambulance protocol with it. | Northeast priority districts, where the nearest documented C-section care is often 100+ km away | When the nearest capable facility is hours away, a known destination saves the most time. |
| 4 | **Site the next dialysis units by need × distance.** Use the dialysis priority list to decide where new units, or verification of existing ones, go first. | The dialysis "service gap" districts | Patients on dialysis travel two to three times a week; distance decides whether they keep up. |
"""

LIMITS = """## Limits, and what we would do next

- **Documented, not actual, capacity.** A facility saying it offers a service is evidence, not proof; availability today is
  never known. The app says so on every card and turns uncertainty into questions to ask by phone.
- **Straight-line distance.** Road travel, especially in hills, is longer; distances are labelled straight-line everywhere.
- **The dataset under-represents public facilities** (88% private, 5% public), so rural gaps are partly data gaps.
- **NFHS-5 is 2019–21** with older district boundaries (the match rate is printed above); it is used only for the planner
  view and never changes a patient's ranking.
- **English-only rules.** Claim classification uses English patterns calibrated on this table.

Next: add public facility registries, road travel time, a phone-confirmation loop so confirmed answers improve future
rankings, and local-language labels for health workers.

Repository: {repo}. Design and evaluation details: `docs/system_design.md`, `docs/evidence_calibration.md`,
`docs/evaluation.md`, `docs/impact.md`.
"""


def build(execute=False):
    module_cells, seen, lines = [], {}, 0
    for name, about in MODULES:
        code = inline_module(name)
        lines += len(code.splitlines())
        for n in top_level_names(code):
            if n in seen:
                raise SystemExit(f'Name clash: {n} is defined in both {seen[n]} and {name}')
            seen[n] = name
        module_cells += [new_markdown_cell(f'**`carematch/{name}.py`** · {about}'), new_code_cell(code)]
    cells = [new_markdown_cell(INTRO.format(repo=REPO, sha=git_sha())), new_code_cell(SETUP),
             new_markdown_cell(PART1.format(lines=lines))] + module_cells

    golden = [(r['id'], r['service'], r['place'], r['place_type']) for r in read_csv('eval/queries.csv')]
    keep = ('service', 'place', 'model_quote_supports', 'model_one_facility', 'xcheck_quote_supports', 'xcheck_one_facility',
            'models_agree', 'human_quote_supports', 'human_one_facility', 'human_note')
    review = {r['id']: {k: r.get(k, '') for k in keep} for r in read_csv('eval/review_sheet.csv')}

    cells += [new_markdown_cell(PART2), new_code_cell(LOAD),
              new_markdown_cell(PART3), new_code_cell(EXPLORE_FIELDS), new_code_cell(EXPLORE_LOCATION),
              new_code_cell(EXPLORE_IDENTITY), new_code_cell(EXPLORE_EVIDENCE),
              new_markdown_cell(PART4), new_code_cell(f'DEMO = {DEMO!r}\n\n' + DEMO_CELL),
              new_markdown_cell(PART5),
              new_code_cell('# Golden queries, embedded from eval/queries.csv: (id, service, place, place type)\n'
                            f'GOLDEN = {golden!r}\n\n' + EVAL_RUN),
              new_code_cell(EVAL_SENSITIVITY),
              new_code_cell('# Review labels, embedded from eval/review_sheet.csv\n'
                            f'REVIEW = {review!r}\n\n' + EVAL_REVIEW),
              new_markdown_cell(PART6), new_code_cell(GAPS_RUN), new_code_cell(GAPS_PRIORITY), new_code_cell(GAPS_FINDINGS),
              new_markdown_cell(ACTIONS), new_markdown_cell(LIMITS.format(repo=REPO))]

    nb = new_notebook(cells=cells, metadata={
        'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
        'language_info': {'name': 'python'}})
    if execute:
        run(nb)
    nbformat.validate(nb)
    nbformat.write(nb, OUT)
    print(f'Wrote {OUT}: {len(cells)} cells' + (' with outputs' if execute else ''))


def run(nb):
    """Execute code cells in one namespace (as a notebook kernel would) and store their printed output."""
    os.environ.setdefault('CAREMATCH_DATA_DIR', os.path.join(ROOT, 'data'))
    ns = {'__name__': '__main__'}
    count = 0
    for cell in nb.cells:
        if cell.cell_type != 'code':
            continue
        count += 1
        out, err = io.StringIO(), io.StringIO()
        started = time.perf_counter()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                exec(compile(cell.source, f'<cell {count}>', 'exec'), ns)
        except Exception:
            cell.outputs = [new_output('error', ename='Error', evalue='see traceback',
                                       traceback=traceback.format_exc().splitlines())]
            cell.execution_count = count
            nbformat.write(nb, OUT)
            raise SystemExit(f'Cell {count} failed; partial notebook written to {OUT}\n' + traceback.format_exc())
        cell.execution_count = count
        cell.outputs = [new_output('stream', name='stdout', text=out.getvalue())] if out.getvalue() else []
        if err.getvalue().strip():
            cell.outputs.append(new_output('stream', name='stderr', text=err.getvalue()))
        print(f'  cell {count:2d} ok ({time.perf_counter() - started:.1f} s)', file=sys.__stdout__)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--execute', action='store_true', help='run every cell on data/*.csv and save the outputs')
    build(parser.parse_args().execute)
