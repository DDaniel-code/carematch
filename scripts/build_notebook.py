"""Build the single-file submission notebook, CareMatch.ipynb, from the repo's source.

    python -m scripts.build_notebook              # write CareMatch.ipynb (no outputs)
    python -m scripts.build_notebook --execute    # also run every cell here on data/*.csv and save the outputs

Part 1 of the notebook is the carematch package itself, inlined module by module, so the notebook, the app and the
tests always run the same code. Modules keep their own namespaces and relative imports.
Golden queries and review labels are embedded from eval/ so the file stands alone.
"""
import argparse
import base64
import contextlib
import csv
import io
import os
import subprocess
import sys
import time
import traceback
import warnings

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook, new_output

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'CareMatch.ipynb')
FIGURES = os.path.join(ROOT, 'docs', 'img')      # each named figure is also saved here for the README
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
    ('price', 'Service-specific prices, bounds, conditions and exact source text.'),
    ('decision', 'Patient-selected preferences and their documented evidence.'),
    ('needs', 'Describe the situation: plain words (English, romanized Hindi with unreviewed spellings) to a suggested service, '
              'urgency and a 108 / 102 danger-sign prompt. Suggests a service; travel preferences stay under user control.'),
    ('review', 'Eight automatic quality checks run on every answer, including citation fidelity: every quote must appear word for word in the '
               'named column of the facility record.'),
    ('recommend', 'The ranking: only Strong or Moderate evidence is recommended; take the nearest distance band (25/75/150/300 km) that has any; '
                  'inside it, stronger evidence first, then distance. Builds cards with quotes, uncertainties, phone, questions to ask, '
                  'runner-ups with the reason they lost, and an honest no-answer.'),
    ('strategy_compare', 'The first choice for each ranking strategy and its source evidence.'),
    ('render', 'Plain-text rendering of a result (used below and in the CLI).'),
    ('datasource', 'Loads the three tables from Spark (Databricks), a SQL warehouse (the app), a Volume snapshot or local CSVs, converting '
                   'every value to the same text so results are identical everywhere.'),
    ('planner', 'District access gaps for planners: distance from every PIN area to the nearest credible facility, joined with NFHS-5 need. '
                'Used only in Part 6; NFHS never affects a patient\'s ranking.'),
    ('calls', 'Branch-specific verification leads and budgeted maximum coverage.'),
    ('lead_model', 'Region-held-out classification of records for verification.'),
]

DEMO = [('Dialysis', 'Patna'), ('MRI scan', 'Darbhanga'), ('Burn care', 'Gaya'), ('Trauma care', 'Kohima'),
        ('Burn care', 'Port Blair')]


# ---- source inlining ------------------------------------------------------------------------------------------------

def inline_module(name):
    path = os.path.join(ROOT, 'carematch', name + '.py')
    with open(path, encoding='utf-8') as src:
        source = src.read()
    # Keep the source readable inside a Python notebook, including its original regex escapes.
    for delimiter in ("'" * 3, '"' * 3):
        if delimiter not in source:
            literal = 'r' + delimiter + source + delimiter
            break
    else:
        literal = repr(source)
    return f'load_embedded({name!r}, {literal})'


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

For planners it answers the next questions: **which districts are far from any facility with credible evidence, do
those districts also show high need** in NFHS-5, **and whom should we phone first to close the gap?**

## What we found

| # | Finding | Where |
| --- | --- | --- |
| 1 | **A keyword match is not a claim.** 5,155 records match C-section keywords; 9% of them carry a claim that the operation is performed. From 93% of India's PIN areas, the nearest keyword match is one of the other 91%. | Part 3, first chart |
| 2 | **Every answer can be checked.** On 38 golden queries, all quality checks pass and every one of the 249 quotes shown appears word for word in the facility record. Where nothing credible is within 300 km, the answer says so. | Parts 4 and 5 |
| 3 | **Documented C-section care is within 50 km of 46% of post offices.** 27 districts are both far from it and have an NFHS-5 caesarean rate below 5%. District caesarean rates fall from 24% to 14% as documented care gets farther away. | Part 6, map |
| 4 | **The obvious call plan helps the wrong places.** Ten verification calls chosen to add the most PIN areas go to districts with a median caesarean rate of 48%. Counting need instead, three calls reach 86 PIN areas in low-caesarean districts; the obvious plan reaches none. | Part 7, last chart |

| Judging criterion | Where in this notebook |
| --- | --- |
| Exploration | Part 3: what a record is, how far each field can be trusted, why a keyword match is not a claim; Part 6: access distance against NFHS-5 |
| Modeling | Parts 1, 4, 5, 7: claim classification, evidence tiers, location confidence, banded ranking, quality checks, evaluation, sensitivity; budgeted maximum coverage; a region-held-out lead model |
| Impact | Parts 6, 7: district access gaps × NFHS need, five actionable insights, and which facilities to verify first, re-planned so the calls go where caesareans are rare |

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
from types import ModuleType
from pathlib import Path
from tempfile import TemporaryDirectory

# Use a private package so importing these modules cannot shadow an installed CareMatch.
package = ModuleType('_carematch_submission')
# Databricks rereads loaded module files after each cell. Keep the exact embedded source
# on the driver for as long as this notebook is running, independent of the workspace path.
embedded_directory = TemporaryDirectory(prefix='carematch_notebook_')
package.__path__ = [embedded_directory.name]
sys.modules[package.__name__] = package

def load_embedded(name, source):
    fullname = package.__name__ + '.' + name
    module = ModuleType(fullname)
    module.__package__ = package.__name__
    path = Path(embedded_directory.name) / (name + '.py')
    path.write_text(source, encoding='utf-8')
    module.__file__ = str(path)
    sys.modules[fullname] = module
    setattr(package, name, module)
    exec(compile(source, module.__file__, 'exec'), module.__dict__)

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

CHARTS = r'''# Charts are optional: every figure below is also printed as a table, so the notebook runs without matplotlib.
try:
    import matplotlib.pyplot as plt
    plt.rcParams.update({'figure.facecolor': '#fcfcfb', 'axes.facecolor': '#fcfcfb', 'savefig.facecolor': '#fcfcfb',
                         'axes.spines.top': False, 'axes.spines.right': False, 'axes.edgecolor': '#b9b8b2',
                         'axes.labelcolor': '#52514e', 'xtick.color': '#52514e', 'ytick.color': '#52514e',
                         'text.color': '#0b0b0b', 'font.size': 10, 'axes.titlesize': 11.5, 'axes.titleweight': 'bold',
                         'axes.titlelocation': 'left', 'legend.frameon': False})
except ImportError:
    plt = None
    print('matplotlib is not installed: charts are skipped, the tables are still printed.')
MUTED, SURFACE = '#52514e', '#fcfcfb'
BLUE_DARK, BLUE, GREY, ORANGE = '#174a8c', '#2a78d6', '#cfcec8', '#eb6834'
DISTANCE_RAMP = ['#cfe1f7', '#8fbbee', '#3f86d9', '#123f7a']      # one hue, light (near) to dark (far)


def spearman(xs, ys):
    """Rank correlation, standard library only (ties share their average rank)."""
    def ranks(values):
        order = sorted(range(len(values)), key=values.__getitem__)
        out, i = [0.0] * len(values), 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return out
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / math.sqrt(
        sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
'''

PART1 = """## Part 1 · The engine

The {lines:,} lines below embed the same modules used by the app. The patient ranking uses deterministic rules.
Part 7 also evaluates a separate statistical model for selecting facilities to verify by phone.
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
    os.environ.setdefault('CAREMATCH_DATA_DIR', os.path.abspath('data'))
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
example = next((index.rows[i].get('name'), m) for i, m in enumerate(index.mixing) if m)
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

FUNNEL_MD = """**Why a keyword search is not enough.** The obvious way to answer "who offers dialysis near me" is to search the
record for the service or its department. The cell below counts those keyword matches for each service, how many of
them carry a claim that the service is actually provided, and, from every PIN area in India, how often the *nearest*
keyword match is one without such a claim.
"""

FUNNEL = r'''areas = [(lat, lon) for pts in districts(index).values() for lat, lon, _ in pts]
funnel = []
for key, spec in SERVICES.items():
    tiers = [a['tier'] for a in index.assessments(key)]
    count = Counter(tiers)
    located = [(index.locations[i]['position'], t) for i, t in enumerate(tiers) if index.locations[i]['position'] and t != 'none']
    mention = PointIndex([(p[0], p[1], t) for p, t in located])
    credible = PointIndex([(p[0], p[1], t) for p, t in located if t != 'weak'])
    unsupported, extra = 0, []
    for lat, lon in areas:
        km, tier = mention.nearest(lat, lon)
        if tier == 'weak':
            unsupported += 1
            extra.append(credible.nearest(lat, lon)[0] - km)
    matches = count['strong'] + count['moderate'] + count['weak']
    funnel.append({'service': spec['label'].split(' (')[0], 'keyword matches': f'{matches:,}', 'strong': count['strong'],
                   'moderate': count['moderate'], 'keyword only': count['weak'],
                   'credible': f"{(count['strong'] + count['moderate']) / matches:.0%}",
                   'nearest match unsupported': f'{unsupported / len(areas):.0%}', '_share': unsupported / len(areas),
                   'median extra km to a credible one': round(statistics.median(extra), 1) if extra else 0})
funnel.sort(key=lambda r: r['_share'])
print(f'From {len(areas):,} PIN areas with a reliable centre:')
show(funnel[::-1], ['service', 'keyword matches', 'strong', 'moderate', 'keyword only', 'credible', 'nearest match unsupported',
                    'median extra km to a credible one'])
worst = funnel[-1]
print(f"\nFor {worst['service']}, {worst['keyword matches']} records match the keywords but only {worst['credible']} carry a claim that the service is provided;")
print(f"from {worst['nearest match unsupported']} of PIN areas the nearest match is one of the others. A credible facility is a median {worst['median extra km to a credible one']} km farther.")

if plt:
    fig, (left, right) = plt.subplots(1, 2, figsize=(12.5, 4.6), num='keyword_vs_claim', sharey=True,
                                      gridspec_kw={'width_ratios': [1.3, 1]})
    y = list(range(len(funnel)))
    start = [0] * len(funnel)
    for col, colour, label in (('strong', BLUE_DARK, 'Strong: two or more direct claims'),
                               ('moderate', BLUE, 'Moderate: one direct or listed claim'),
                               ('keyword only', GREY, 'Keyword only: a department, a referral, outsourced, or a passing mention')):
        values = [r[col] for r in funnel]
        left.barh(y, values, left=start, color=colour, edgecolor=SURFACE, linewidth=1.5, height=0.62, label=label)
        start = [a + b for a, b in zip(start, values)]
    for i, r in enumerate(funnel):
        left.text(start[i] + 70, i, f"{r['credible']} credible", va='center', color=MUTED, fontsize=9)
    left.set_yticks(y)
    left.set_yticklabels([r['service'] for r in funnel])
    left.set_xlim(0, max(start) * 1.17)
    left.set_xlabel('facilities whose record matches the service keywords')
    left.set_title('A keyword match is not a claim')
    left.legend(loc='upper center', bbox_to_anchor=(0.42, -0.16), fontsize=8.5)
    right.barh(y, [r['_share'] * 100 for r in funnel], color=BLUE, height=0.62)
    for i, r in enumerate(funnel):
        right.text(r['_share'] * 100 + 1.5, i, f"{r['nearest match unsupported']} · +{r['median extra km to a credible one']:.0f} km",
                   va='center', color=MUTED, fontsize=9)
    right.set_xlim(0, 125)
    right.set_xticks([0, 25, 50, 75, 100])
    right.set_xlabel('% of PIN areas whose nearest keyword match has no claim\n(+km: median extra distance to a credible facility)')
    right.set_title('The nearest match is usually one of the grey ones')
    fig.tight_layout()
    plt.show()
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
counts = [len(r.get('review', {}).get('checks', [])) for *_, r in runs]
span = f'{min(counts)}' if min(counts) == max(counts) else f'{min(counts)}–{max(counts)}'
print(f'All quality checks passed ({span} checks per answer): '
      f'{sum(1 for *_, r in runs if r.get("review", {}).get("passed"))}/{len(runs)}'
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

For every India Post PIN area with a reliable centre (14,917 areas, 702 districts, weighted by number of post offices as a
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

ACCESS_MAP = r'''credible_cs = PointIndex(credible_points(index, 'c_section'))
pin_km = [(lat, lon, credible_cs.nearest(lat, lon)[0]) for pts in districts(index).values() for lat, lon, _ in pts]
bins = [('within 25 km', 0, 25), ('25–50 km', 25, 50), ('50–100 km', 50, 100), ('over 100 km', 100, float('inf'))]


def district_median_km(points):
    """{(district, state): median km from its PIN areas to the nearest of these points}."""
    nearest = PointIndex(points)
    return {key: statistics.median(nearest.nearest(lat, lon)[0] for lat, lon, _ in pts) for key, pts in districts(index).items()}


rate = {(r['district'], r['state']): r['csection_pct'] for r in table if r['csection_pct'] is not None}
to_credible, to_any_hospital = district_median_km(credible_points(index, 'c_section')), district_median_km(hospital_points(index))
keys = sorted(rate)
print(f'{len(keys)} districts with an NFHS-5 caesarean rate, grouped by median distance to documented C-section care:')
gradient = []
for label, lo, hi in bins:
    values = sorted(rate[k] for k in keys if lo <= to_credible[k] < hi)
    q = statistics.quantiles(values, n=4)
    gradient.append({'median km to documented care': label, 'districts': len(values), 'median caesarean rate %': round(q[1], 1),
                     'middle half': f'{q[0]:.1f}–{q[2]:.1f}', '_q': q})
show(gradient, ['median km to documented care', 'districts', 'median caesarean rate %', 'middle half'])
rho_credible = spearman([to_credible[k] for k in keys], [rate[k] for k in keys])
rho_hospital = spearman([to_any_hospital[k] for k in keys], [rate[k] for k in keys])
print(f'\nRank correlation with the caesarean rate: distance to documented C-section care {rho_credible:+.2f}, '
      f'distance to any hospital listing {rho_hospital:+.2f}.')
print('An independent survey agrees with the direction of our access measure: the farther a district is from documented care,')
print('the fewer caesareans its women receive. The same gradient appears for any hospital listing, so it shows where listed')
print('facilities are, not that our evidence tiers are validated; and it is an association, not a cause (cities have both).')

if plt:
    fig, (left, right) = plt.subplots(1, 2, figsize=(12.5, 6.2), num='access_gap_map', gridspec_kw={'width_ratios': [1.15, 1]})
    for (label, lo, hi), colour in zip(bins, DISTANCE_RAMP):
        pts = [(lon, lat) for lat, lon, km in pin_km if lo <= km < hi]
        left.scatter([p[0] for p in pts], [p[1] for p in pts], s=3.2, color=colour, linewidths=0,
                     label=f'{label} ({len(pts) / len(pin_km):.0%} of PIN areas)')
    left.scatter([r['lon'] for r in maternal], [r['lat'] for r in maternal], s=95, facecolors='none', edgecolors=ORANGE,
                 linewidths=1.8)
    left.plot([], [], linestyle='none', marker='o', markersize=3.2, markerfacecolor='none', markeredgecolor=ORANGE,
              markeredgewidth=0.6, label=f'{len(maternal)} priority districts: far, caesarean rate below 5%')
    left.set_aspect(1 / math.cos(math.radians(22)))
    left.set_xlim(67.5, 98)
    left.set_ylim(6, 37.5)
    left.set_xticks([])
    left.set_yticks([])
    for side in ('left', 'bottom'):
        left.spines[side].set_visible(False)
    left.set_title('Straight-line distance to the nearest facility\nthat documents C-section care')
    left.legend(loc='upper center', bbox_to_anchor=(0.5, 0.02), fontsize=8.5, ncol=2, columnspacing=1.2, handletextpad=0.3,
                markerscale=3)
    x = list(range(len(gradient)))
    right.bar(x, [g['_q'][1] for g in gradient], color=DISTANCE_RAMP, edgecolor='#8fbbee', linewidth=0.6, width=0.62)
    right.vlines(x, [g['_q'][0] for g in gradient], [g['_q'][2] for g in gradient], color=MUTED, linewidth=1.2)
    for i, g in enumerate(gradient):
        right.text(i + 0.36, g['_q'][1], f"{g['_q'][1]:.0f}%", va='center', fontsize=10)
    right.axhline(10, color=MUTED, linewidth=0.9, linestyle=(0, (4, 3)))
    right.text(len(x) - 0.5, 9.5, 'WHO: up to about\n10%, more caesareans\ngo with fewer deaths', va='top', color=MUTED, fontsize=8.5)
    right.set_xticks(x)
    right.set_xticklabels([f"{g['median km to documented care']}\n{g['districts']} districts" for g in gradient])
    right.tick_params(axis='x', length=0)
    right.set_xlim(-0.6, len(x) + 0.75)
    right.set_xlabel("district's median distance to documented C-section care")
    right.set_ylim(0, None)
    right.set_ylabel('NFHS-5 district caesarean rate, % (median, middle half)')
    right.set_title('Fewer caesareans where documented care is far')
    fig.tight_layout()
    plt.show()
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

ACTIONS = """### Actionable insights: recommended actions

| # | Action | Where | Why |
| --- | --- | --- | --- |
| 1 | **Fix the data before building.** Add public facilities (district hospitals, CHCs / First Referral Units, national dialysis programme centres) with their documented services. | The "data gap" districts above | The gap may be in the listing, not on the ground. Once added, CareMatch shows them to health workers with no code change. |
| 2 | **Verify, then upgrade, surgical obstetric capacity.** Confirm by phone which listed hospitals can do an emergency caesarean (CareMatch prints the questions); where none can, prioritise the district hospital for emergency obstetric staffing (obstetrician, anaesthetist, blood storage). | The maternal "service gap" districts, and districts where births happen in facilities but caesareans are rare | High institutional births with a very low caesarean rate points to missing surgical capacity, not missing buildings. |
| 3 | **Pre-arranged referral routes and transport.** Name the nearest facility with credible evidence for each priority district (CareMatch's answer from the district centre) and agree a referral and ambulance protocol with it. | Northeast priority districts, where the nearest documented C-section care is often 100+ km away | When the nearest capable facility is hours away, a known destination saves the most time. |
| 4 | **Site the next dialysis units by need × distance.** Use the dialysis priority list to decide where new units, or verification of existing ones, go first. | The dialysis "service gap" districts | Patients on dialysis travel two to three times a week; distance decides whether they keep up. |
| 5 | **Make this week's verification calls where caesareans are rare.** Phone the facilities of the need-targeted plan in Part 7, starting with Darbhanga Medical College, Katihar Medical College and Jyothi Hospital (Mayurbhanj); CareMatch prints the questions to ask. | Low-caesarean districts of Bihar, Odisha, Rajasthan, Assam, Madhya Pradesh, Uttar Pradesh and Nagaland | Ten confirmed calls would bring documented C-section care within 50 km of 205 PIN areas in districts with a caesarean rate below 10%; the same ten calls chosen by PIN count reach 20. |
"""

LIMITS = """## Limits, and what we would do next

- **Documented, not actual, capacity.** A facility saying it offers a service is evidence, not proof; availability today is
  never known. The app says so on every card and turns uncertainty into questions to ask by phone.
- **Straight-line distance.** Road travel, especially in hills, is longer; distances are labelled straight-line everywhere.
- **The dataset under-represents public facilities** (88% private, 5% public), so rural gaps are partly data gaps.
- **NFHS-5 is 2019–21** with older district boundaries (the match rate is printed above); it is used only for the planner
  view and never changes a patient's ranking.
- **English-only rules.** Claim classification uses English patterns calibrated on this table.
- **Prices are rarely documented.** Only a handful of records state a patient price for the service itself, so the
  price order usually falls back to distance and says so; a price is shown only as quoted, with its unit and conditions.
- **Verification leads are leads.** The call plan and the lead model choose whom to phone; neither changes what a patient
  is recommended, and coverage gains assume the facility confirms the service.

Next: add public facility registries, road travel time, a phone-confirmation loop so confirmed answers improve future
rankings, and local-language labels for health workers.

Repository: {repo}. Design and evaluation details: `docs/system_design.md`, `docs/evidence_calibration.md`,
`docs/evaluation.md`, `docs/impact.md`.
"""


PART7 = """## Part 7 · Which choice changes, and where should a planner call first?

Short demonstrations built on the same engine. None of them changes what a patient is recommended.
"""

PART7_NEEDS = """**Describe the situation.** A health worker can type what is happening instead of picking a service. The lexicon
suggests a service and urgency, quotes the words it matched, and puts "call 108 / 102" first for danger signs. In the
app it suggests a service for the user to confirm. The user selects any travel preference. Hindi entries are romanized with unreviewed spellings.
"""

NEEDS_DEMO = '''from _carematch_submission.needs import interpret_need
for phrase in ['heavy bleeding after delivery', 'road accident, head injury', 'kidney patient needs dialysis twice a week',
               'burns from a road accident', 'fever and cough', 'bachcha saans nahi le raha (romanized Hindi, unreviewed spelling)']:
    x = interpret_need(phrase)
    print(f"{phrase!r:70} -> {x['status']:9} {str(x['service']):10} urgency={str(x['urgency']):13} "
          f"red_flag={x['red_flag']}" + (f"  also: {', '.join(x['also_possible'])}" if x['also_possible'] else ''))'''

PART7_COMPARE = """**Same search, three orders.** Best evidence, nearest and compare-listed-prices can put different facilities first.
The comparison names each first choice with its quote, and says when the starting point is too approximate to trust
a small distance difference.
"""

PART7_CALLS = """**Ten calls, most new coverage.** For C-section within 50 km, 7,402 of 14,008 reliably located PIN areas already
have a facility with credible evidence. Each candidate below has obstetric or surgical leads but no credible C-section
claim. Choosing greedily (each call adds the most still-uncovered PINs) is compared with simply taking the candidates
with the largest individual reach, which overlap. Gains assume the facility confirms the service.
"""

PART7_NEED = """**Then we checked where those calls go, and changed the objective.** Counting every PIN equally rewards dense, well-served
regions: Kerala has many small PINs, and it also has one of India's highest caesarean rates. The cell below joins each PIN
to its district's NFHS-5 caesarean rate and re-plans the same ten calls, counting only PINs in districts where the rate is
below 10% (WHO: at population level, rates up to about 10% are associated with fewer maternal and newborn deaths). This is
the one place where all three tables meet in a single decision: facility text decides who is a lead, the PIN directory
decides who gains coverage, and NFHS decides whose coverage matters most.
"""

NEED_DEMO = '''from _carematch_submission.calls import LOW_CSECTION_TARGET_PCT, need_target, pin_need
need = pin_need(coverage['pins'], nfhs_rows)
target = need_target(need)
need_plan = greedy_plan(leads, budget=10, target=target)
reached = [need[p] for step in plan for p in step['new_pins'] if need[p] is not None]
print(f'The ten PIN-count calls add coverage in districts with a median caesarean rate of {statistics.median(reached):.1f}%.')
print(f'{len(target):,} PINs lie in districts with a rate below {LOW_CSECTION_TARGET_PCT:g}%; '
      f'{len(target - coverage["covered"]):,} of them have no documented C-section care within 50 km.')
rows = []
for k in (3, 5, 10):
    by_count = set().union(*(step['new_pins'] for step in plan[:k]))
    by_need = need_plan[:k]
    rows.append({'calls': k, 'PIN-count plan: all PINs': len(by_count), 'of which low-caesarean': len(by_count & target),
                 'need plan: low-caesarean PINs': sum(step['marginal_gain'] for step in by_need),
                 'need plan: all PINs': sum(step['marginal_gain'] + len(step['other_new_pins']) for step in by_need)})
show(rows, list(rows[0]))
print('\\nNeed-targeted call order:')
for step in need_plan[:5]:
    c = step['candidate']
    rates = [need[p] for p in step['new_pins']]
    where = Counter(coverage['pins'][p]['district'].title() for p in step['new_pins']).most_common(2)
    print(f"  {step['rank']}. {c['name']} ({c['state']}): +{step['marginal_gain']} PINs in "
          + ', '.join(d for d, _ in where) + f" · district caesarean rate {statistics.median(rates):.1f}% · lead: {c['leads'][0][2][:60]!r}")

if plt:
    fig, (left, right) = plt.subplots(1, 2, figsize=(12.5, 4.1), num='call_plans')
    ks = list(range(1, 11))
    greedy = [plan[min(k, len(plan)) - 1]['cumulative_gain'] for k in ks]
    largest = [topk_baseline(leads, k)['unique_new_pins'] for k in ks]
    left.plot(ks, greedy, color=BLUE, linewidth=2, marker='o', markersize=5)
    left.plot(ks, largest, color='#8a8983', linewidth=2, marker='o', markersize=5)
    left.text(10.25, greedy[-1], f'Deduct overlap\\neach call: {greedy[-1]}', va='center', fontsize=9)
    left.text(10.25, largest[-1], f'Ten largest\\nindividual gains: {largest[-1]}', va='center', fontsize=9, color=MUTED)
    left.set_title('Overlap decides how much ten calls add')
    left.set_ylabel('PIN areas newly within 50 km, if confirmed')
    count_hits = [len(set().union(*(step['new_pins'] for step in plan[:k])) & target) for k in ks]
    need_hits = [need_plan[min(k, len(need_plan)) - 1]['cumulative_gain'] for k in ks]
    right.plot(ks, need_hits, color=ORANGE, linewidth=2, marker='o', markersize=5)
    right.plot(ks, count_hits, color=BLUE, linewidth=2, marker='o', markersize=5)
    right.text(10.25, need_hits[-1], f'Count need: {need_hits[-1]}', va='center', fontsize=9)
    right.text(10.25, count_hits[-1], f'Count every PIN\\nequally: {count_hits[-1]}', va='center', fontsize=9)
    right.set_title('The objective decides who gains')
    right.set_ylabel('newly covered PIN areas in districts\\nwith a caesarean rate below 10%')
    for ax in (left, right):
        ax.set_xlim(0.6, 13.4)
        ax.set_xticks(ks)
        ax.set_ylim(0, None)
        ax.set_xlabel('verification calls')
        ax.grid(axis='y', color='#e6e5df', linewidth=0.8)
        ax.set_axisbelow(True)
    fig.tight_layout()
    plt.show()'''

PART7_LEADS = """**A statistical second opinion on whom to verify.** A logistic regression is trained with Strong C-section evidence
as a proxy positive and every other record unlabeled, using no C-section or maternity wording at all, and is evaluated
on whole regions of India it never saw. It is compared with a simple rule (hospitals first, then more specialties).
"""

STRATEGY_DEMO = '''from _carematch_submission.strategy_compare import compare_strategies
service, place = 'dialysis', 'Delhi'
comparison = compare_strategies(index, service, place, recommend(index, service, place))
print(place, service, comparison['summary'], sep=' · ')
for opt in comparison['options']:
    print(opt['label'], opt['name'], opt['distance_km'], opt['tier'])
    if opt['citation']:
        print(' ', opt['facility_id'], opt['citation']['field'], opt['citation']['quote'])'''

CALL_DEMO = '''from _carematch_submission.calls import current_coverage, candidates, greedy_plan, topk_baseline
coverage = current_coverage(index)
leads, checks = candidates(index, cov=coverage)
plan = greedy_plan(leads, budget=10)
print('Possible extra PIN coverage if the selected facilities confirm the service, within 50 km.')
for k in (3, 5, 10):
    actual = plan[:k]
    print(k, 'calls:', sum(step['marginal_gain'] for step in actual), 'PINs; independent-gain baseline:',
          topk_baseline(leads, k)['unique_new_pins'])
if plan:
    first = plan[0]['candidate']
    followup = greedy_plan(leads, budget=2, exclude=[first['facility_id']])
    print('If the first call answers no, two calls remain:', sum(r['marginal_gain'] for r in followup), 'potential PINs.')
    for step in plan[:3]:
        print(step['candidate']['name'], step['marginal_gain'], step['candidate']['leads'][:1])'''

LEAD_DEMO = '''from _carematch_submission.lead_model import build_dataset, cross_validate, baseline_scores, metrics
data = build_dataset(index)
scores, _ = cross_validate(data, C=0.3)
print('Region-held-out recovery of proxy positives. Actual availability requires a call.')
for name, predictions in [('Logistic regression', scores), ('Hospital and specialty baseline', baseline_scores(data))]:
    result = metrics(data['y'], predictions)
    print(f"{name}: ROC-AUC {result['roc_auc']}, PR-AUC {result['pr_auc']} (base rate {result['prevalence']}), "
          f"precision@50 {result['precision_at_50']}, precision@200 {result['precision_at_200']}")'''


def build(execute=False):
    module_cells, lines = [], 0
    for name, about in MODULES:
        code = inline_module(name)
        lines += len(code.splitlines())
        module_cells += [new_markdown_cell(f'**`carematch/{name}.py`** · {about}'), new_code_cell(code)]
    cells = [new_markdown_cell(INTRO.format(repo=REPO, sha=git_sha())), new_code_cell(SETUP),
             new_markdown_cell(PART1.format(lines=lines))] + module_cells

    golden = [(r['id'], r['service'], r['place'], r['place_type']) for r in read_csv('eval/queries.csv')]
    keep = ('service', 'place', 'model_quote_supports', 'model_one_facility', 'xcheck_quote_supports', 'xcheck_one_facility',
            'models_agree', 'human_quote_supports', 'human_one_facility', 'human_note')
    review = {r['id']: {k: r.get(k, '') for k in keep} for r in read_csv('eval/review_sheet.csv')}

    cells += [new_code_cell("""from _carematch_submission.datasource import load, load_nfhs
from _carematch_submission.textutil import is_empty, normalize
from _carematch_submission.services import SERVICES
from _carematch_submission.recommend import CareIndex, recommend
from _carematch_submission.render import to_text
from _carematch_submission.planner import (PointIndex, credible_points, district_table, districts, dialysis_priorities,
                                            gap_kind, hospital_points, maternal_priorities)"""),
              new_code_cell(CHARTS),
              new_markdown_cell(PART2), new_code_cell(LOAD),
              new_markdown_cell(PART3), new_code_cell(EXPLORE_FIELDS), new_code_cell(EXPLORE_LOCATION),
              new_code_cell(EXPLORE_IDENTITY), new_code_cell(EXPLORE_EVIDENCE),
              new_markdown_cell(FUNNEL_MD), new_code_cell(FUNNEL),
              new_markdown_cell(PART4), new_code_cell(f'DEMO = {DEMO!r}\n\n' + DEMO_CELL),
              new_markdown_cell(PART5),
              new_code_cell('# Golden queries, embedded from eval/queries.csv: (id, service, place, place type)\n'
                            f'GOLDEN = {golden!r}\n\n' + EVAL_RUN),
              new_code_cell(EVAL_SENSITIVITY),
              new_code_cell('# Review labels, embedded from eval/review_sheet.csv\n'
                            f'REVIEW = {review!r}\n\n' + EVAL_REVIEW),
              new_markdown_cell(PART6), new_code_cell(GAPS_RUN), new_code_cell(GAPS_PRIORITY), new_code_cell(ACCESS_MAP), new_code_cell(GAPS_FINDINGS),
              new_markdown_cell(ACTIONS),
              new_markdown_cell(PART7), new_markdown_cell(PART7_NEEDS), new_code_cell(NEEDS_DEMO),
              new_markdown_cell(PART7_COMPARE), new_code_cell(STRATEGY_DEMO),
              new_markdown_cell(PART7_CALLS), new_code_cell(CALL_DEMO),
              new_markdown_cell(PART7_NEED), new_code_cell(NEED_DEMO),
              new_markdown_cell(PART7_LEADS), new_code_cell(LEAD_DEMO),
              new_markdown_cell(LIMITS.format(repo=REPO))]

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
    os.environ['MPLBACKEND'] = 'Agg'                   # figures are collected after each cell, never shown in a window
    warnings.filterwarnings('ignore', message='.*non-interactive.*')
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
        cell.outputs += figures()
        print(f'  cell {count:2d} ok ({time.perf_counter() - started:.1f} s)', file=sys.__stdout__)


def figures():
    """Open matplotlib figures as notebook image outputs; a named figure is also saved under docs/img/ for the README."""
    plt = sys.modules.get('matplotlib.pyplot')
    outputs = []
    for number in (plt.get_fignums() if plt else []):
        fig = plt.figure(number)
        png = io.BytesIO()
        fig.savefig(png, format='png', dpi=150)
        if fig.get_label():
            os.makedirs(FIGURES, exist_ok=True)
            with open(os.path.join(FIGURES, fig.get_label() + '.png'), 'wb') as out:
                out.write(png.getvalue())
        outputs.append(new_output('display_data', data={'image/png': base64.b64encode(png.getvalue()).decode('ascii'),
                                                         'text/plain': f'<Figure: {fig.get_label() or number}>'}))
        plt.close(fig)
    return outputs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--execute', action='store_true', help='run every cell on data/*.csv and save the outputs')
    build(parser.parse_args().execute)
