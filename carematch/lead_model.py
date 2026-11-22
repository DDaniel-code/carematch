"""C-section verification leads: which facilities look like ones that document caesarean delivery, but do not?

Positive-unlabeled setup. Facilities whose records give Strong evidence for C-section are proxy positives; every other
record is unlabeled (it may well offer the service without saying so). A logistic regression learns what distinguishes
the proxy positives using only features that cannot spell out the label:

  * no C-section or maternity vocabulary: every claim fragment, description sentence or specialty that matches BLOCK is
    removed before any feature is computed, so adding or deleting such text cannot change a facility's features;
  * nothing derived from the label: no evidence tier, claim kind or count of service claims is a feature.

Evaluation holds out whole regions of India (leave-one-region-out) and keeps every facility group (duplicate listings,
same-name branches) inside a single fold, so a facility's twin never sits on the other side of the split.

Scores rank facilities for a planner's verification calls. They are not evidence that a facility offers the service.
numpy and scikit-learn are imported lazily so the engine itself stays standard-library only.
"""
import math
import re
from collections import Counter

from .geo import canonical_state
from .services import INCOMPATIBLE_TYPES
from .textutil import fragments, normalize, source_urls, split_camel, text

SERVICE = 'c_section'
CURRENT_YEAR = 2026
USE_NOTE = ('Planner verification lead from a statistical model, not evidence that this facility offers C-section. '
            'Confirm by phone before any referral.')

# Service and maternity vocabulary. Any text that matches is invisible to the model.
BLOCK = re.compile(
    r'caesar|cesar|\bc[- ]?sections?\b|\blscs\b|cemonc|obstet|gyn(a)?ec|matern|deliver|labou?r\s*(room|ward|suite)|'
    r'pregnan|natal|neonat|newborn|\bnicu\b|\bsncu\b|perinat|fetal|foetal|infertil|fertility|\bivf\b|reproductive|'
    r'midwi|birth|anaesth|anesth|blood\s*bank|\bwomen|\bmother|\bobg\b|\bob[/ -]?gyn', re.I)

# Generic capability signals, matched only in fragments that survived BLOCK. None of them names the service.
INDICATORS = {
    'icu': (r'\bicu\b|\biccu\b|intensive care|critical care', 'mentions an ICU or critical care'),
    'operation_theatre': (r'operation theat|operating (room|theat)|\bot\b|\bots\b|modular theat|surgical suite',
                          'mentions an operation theatre'),
    'ventilator': (r'ventilator', 'mentions ventilators'),
    'round_the_clock': (r'24\s*[x/×]\s*7|24 hours|round[- ]the[- ]clock|24-hour', 'mentions round-the-clock service'),
    'ambulance': (r'ambulance', 'mentions an ambulance'),
    'imaging_ct_mri': (r'\bct\b|computed tomography|\bmri\b|magnetic resonance', 'mentions CT or MRI'),
    'ultrasound': (r'ultraso|sonograph', 'mentions ultrasound'),
    'laparoscopy': (r'laparoscop|endoscop', 'mentions laparoscopy or endoscopy'),
    'dialysis': (r'dialy', 'mentions dialysis'),
    'laboratory': (r'laborator|\blab\b|pathology', 'mentions a laboratory'),
    'inpatient': (r'\bwards?\b|\bbeds?\b|inpatient|\bipd\b|admission', 'mentions inpatient beds or wards'),
    'insurance': (r'insurance|cashless|ayushman|pm-?jay|cghs|\btpa\b', 'mentions insurance or cashless schemes'),
    'surgery': (r'surger|surgical|operat(e|ion|ive)', 'mentions surgery'),
}
_INDICATOR_RE = {k: re.compile(p, re.I) for k, (p, _) in INDICATORS.items()}
CLAIM_FIELDS = ('procedure', 'equipment', 'capability')

# Specialty families (first match wins). Counting families instead of 2,900 individual enum values keeps coefficients
# stable and explanations readable ("lists 6 surgical specialties").
SPECIALTY_FAMILIES = [
    ('dental', r'dent|odont|maxillofacial|oral'),
    ('eye', r'ophthalm|retina|cornea|glaucoma|cataract|strabism|ocul|refractive|vitreo'),
    ('alternative', r'ayurved|homeo|unani|siddha|naturopath|yoga'),
    ('emergency_critical', r'emergency|critical care|trauma|intensiv'),
    ('surgical', r'surg|urolog|orthop'),
    ('pediatric', r'pediatric|paediatric|child'),
    ('diagnostic', r'radiolog|patholog|imaging|laborator|nuclear'),
    ('internal_medicine', r'internal medicine|family medicine|general medicine|general practice'),
    ('medical_specialty', r'cardio|nephro|neuro|gastro|pulmon|endocrin|oncolog|hematolog|rheumat|infectious|hepat|'
                          r'dermat|psychiat|allerg|geriatric|sleep'),
]
_FAMILY_RE = [(k, re.compile(p, re.I)) for k, p in SPECIALTY_FAMILIES]
FAMILY_LABEL = {'dental': 'dental', 'eye': 'eye-care', 'alternative': 'traditional-medicine',
                'emergency_critical': 'emergency or critical-care', 'surgical': 'surgical', 'pediatric': 'paediatric',
                'diagnostic': 'diagnostic', 'internal_medicine': 'general-medicine', 'medical_specialty': 'medical',
                'other': 'other'}

REGIONS = {
    'North': ['Jammu And Kashmir', 'Ladakh', 'Himachal Pradesh', 'Punjab', 'Chandigarh', 'Haryana', 'Delhi',
              'Uttarakhand', 'Uttar Pradesh', 'Rajasthan'],
    'West': ['Gujarat', 'Maharashtra', 'Goa', 'The Dadra And Nagar Haveli And Daman And Diu'],
    'Central': ['Madhya Pradesh', 'Chhattisgarh'],
    'East': ['Bihar', 'Jharkhand', 'Odisha', 'West Bengal'],
    'Northeast': ['Assam', 'Arunachal Pradesh', 'Manipur', 'Meghalaya', 'Mizoram', 'Nagaland', 'Tripura', 'Sikkim'],
    'South': ['Andhra Pradesh', 'Telangana', 'Karnataka', 'Kerala', 'Tamil Nadu', 'Puducherry', 'Lakshadweep',
              'Andaman And Nicobar Islands'],
}
STATE_REGION = {s: r for r, states in REGIONS.items() for s in states}


def blocked(value):
    """True when the text names the service or maternity care, read both as written and with camelCase split
    (the split catches "gynecologyAndObstetrics"; the raw form keeps acronyms such as "CEmONC" whole)."""
    raw = text(value)
    return bool(BLOCK.search(raw) or BLOCK.search(split_camel(raw)))


def _number(value, low, high):
    m = re.search(r'\d+(\.\d+)?', text(value).replace(',', ''))
    v = float(m.group(0)) if m else None
    return v if v is not None and low <= v <= high else None


def _sentences(value):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text(value)) if s.strip()]


def specialty_family(name):
    words = split_camel(name).lower()
    return next((k for k, rx in _FAMILY_RE if rx.search(words)), 'other')


def facility_features(row):
    """(features, citations) for one record. citations[name] = (field, verbatim text) behind a non-zero feature."""
    f, cite = {}, {}
    ftype = normalize(row.get('facilityTypeId'))
    f['type_hospital'] = float(ftype == 'hospital')
    f['type_clinic'] = float(ftype == 'clinic')
    f['type_other'] = float(ftype not in ('hospital', 'clinic'))
    if ftype:
        cite['type_hospital' if ftype == 'hospital' else 'type_clinic' if ftype == 'clinic' else 'type_other'] = \
            ('facilityTypeId', text(row.get('facilityTypeId')))
    op = normalize(row.get('operatorTypeId'))
    f['operator_public'] = float(op == 'public')
    f['operator_private'] = float(op == 'private')
    if op in ('public', 'private'):
        cite[f'operator_{op}'] = ('operatorTypeId', text(row.get('operatorTypeId')))

    for name, field, low, high in (('beds', 'capacity', 1, 5000), ('doctors', 'numberDoctors', 1, 2000)):
        v = _number(row.get(field), low, high)
        f[f'log_{name}'] = math.log1p(v) if v else 0.0
        f[f'{name}_missing'] = float(v is None)
        if v:
            cite[f'log_{name}'] = (field, text(row.get(field)))
    year = _number(row.get('yearEstablished'), 1800, CURRENT_YEAR)
    f['log_age'] = math.log1p(CURRENT_YEAR - year) if year else 0.0
    f['age_missing'] = float(year is None)
    if year:
        cite['log_age'] = ('yearEstablished', text(row.get('yearEstablished')))

    f['has_phone'] = float(bool(fragments(row.get('phone_numbers')) or text(row.get('officialPhone')) not in ('', 'null')))
    f['has_website'] = float(text(row.get('officialWebsite')) not in ('', 'null'))
    f['log_sources'] = math.log1p(len(source_urls(row.get('source_urls'))))
    followers = _number(row.get('engagement_metrics_n_followers'), 0, 1e9)
    f['log_followers'] = math.log1p(followers) if followers else 0.0

    specs = [s for s in dict.fromkeys(fragments(row.get('specialties'))) if not blocked(s)]
    families = {}
    for s in specs:
        families.setdefault(specialty_family(s), []).append(s)
    for fam in [k for k, _ in SPECIALTY_FAMILIES] + ['other']:
        members = families.get(fam, [])
        f[f'spec_{fam}'] = math.log1p(len(members))
        if members:
            cite[f'spec_{fam}'] = ('specialties', ', '.join(members[:6]) + (' …' if len(members) > 6 else ''))

    kept = []
    for field in CLAIM_FIELDS:
        items = [x for x in fragments(row.get(field)) if not blocked(x)]
        f[f'log_{field}_items'] = math.log1p(len(items))
        kept += [(field, x) for x in items]
    sentences = [s for s in _sentences(row.get('description')) if not blocked(s)]
    f['log_description_words'] = math.log1p(sum(len(s.split()) for s in sentences))
    kept += [('description', s) for s in sentences]
    for name, rx in _INDICATOR_RE.items():
        hit = next(((field, x) for field, x in kept if rx.search(x)), None)
        f[f'ind_{name}'] = float(hit is not None)
        if hit:
            cite[f'ind_{name}'] = hit
    return f, cite


def feature_label(name, row, value=None):
    if name.startswith('spec_'):
        n = round(math.expm1(value)) if value is not None else None
        return f"lists {n if n is not None else 'some'} {FAMILY_LABEL[name[5:]]} specialt{'y' if n == 1 else 'ies'}"
    if name.startswith('ind_'):
        return INDICATORS[name[4:]][1]
    labels = {
        'type_hospital': 'listed as a hospital', 'type_clinic': 'listed as a clinic', 'type_other': 'other facility type',
        'operator_public': 'public operator', 'operator_private': 'private operator',
        'log_beds': f"{text(row.get('capacity'))} beds listed", 'beds_missing': 'bed count missing',
        'log_doctors': f"{text(row.get('numberDoctors'))} doctors listed", 'doctors_missing': 'doctor count missing',
        'log_age': f"established {text(row.get('yearEstablished'))}", 'age_missing': 'founding year missing',
        'has_phone': 'phone number listed', 'has_website': 'official website listed',
        'log_sources': 'number of source pages', 'log_followers': 'social media followers',
        'log_specialties': 'number of specialties listed', 'log_description_words': 'length of description',
    }
    if name in labels:
        return labels[name]
    m = re.match(r'log_(\w+)_items', name)
    return f'number of {m.group(1)} items' if m else name


# ---- groups and geography ---------------------------------------------------------------------------------------------

def facility_groups(index):
    """Group id per row: duplicate listings (engine) joined with records that share a normalized name (branches)."""
    parent = list(range(len(index.rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        parent[find(b)] = find(a)

    first = {}
    for i, r in enumerate(index.rows):
        for key in (('dup', index.dup_group[i]), ('name', re.sub(r'[^a-z0-9]+', ' ', normalize(r.get('name'))).strip())):
            if key[0] == 'name' and key[1] in ('', 'null', 'none'):
                continue
            if key in first:
                union(first[key], i)
            else:
                first[key] = i
    return [find(i) for i in range(len(index.rows))]


def row_region(index, i):
    state = index.locations[i].get('state') or canonical_state(index.rows[i].get('address_stateOrRegion'))
    return STATE_REGION.get(state, 'Unknown')


def group_regions(index, groups):
    """Region of each row's group (majority region of its members), so a group never straddles folds."""
    members = {}
    for i, g in enumerate(groups):
        members.setdefault(g, []).append(row_region(index, i))
    vote = {g: (Counter(r for r in regs if r != 'Unknown').most_common(1) or [('Unknown', 0)])[0][0]
            for g, regs in members.items()}
    return [vote[g] for g in groups], sum(1 for i, g in enumerate(groups) if row_region(index, i) != vote[g])


# ---- data, model, evaluation ------------------------------------------------------------------------------------------

def build_dataset(index):
    """Feature matrix inputs, proxy labels and fold keys for every facility."""
    feats, cites = zip(*(facility_features(r) for r in index.rows))
    names = list(feats[0])
    tiers = [a['tier'] for a in index.assessments(SERVICE)]
    groups = facility_groups(index)
    regions, moved = group_regions(index, groups)
    return {'names': names, 'X': [[f[n] for n in names] for f in feats], 'citations': list(cites),
            'y': [int(t == 'strong') for t in tiers], 'tiers': tiers, 'groups': groups, 'regions': regions,
            'rows_moved_to_group_region': moved}


def make_model(C=0.3):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(StandardScaler(), LogisticRegression(C=C, class_weight='balanced', max_iter=5000))


def cross_validate(data, labels=None, C=0.3):
    """Leave-one-region-out out-of-fold scores, plus each row's held-out model (for explanations)."""
    import numpy as np
    X, y = np.asarray(data['X']), np.asarray(labels if labels is not None else data['y'])
    regions = np.asarray(data['regions'])
    oof, fold_model = np.full(len(y), np.nan), {}
    for region in sorted(set(regions)):
        test = regions == region
        train = ~test
        if y[train].sum() == 0 or y[train].sum() == train.sum():
            continue
        model = make_model(C).fit(X[train], y[train])
        oof[test] = model.predict_proba(X[test])[:, 1]
        fold_model[region] = model
    return oof, fold_model


def baseline_scores(data):
    """Simple rule: hospitals first, then more listed (non-maternity) specialties."""
    names = data['names']
    h = names.index('type_hospital')
    spec = [j for j, n in enumerate(names) if n.startswith('spec_')]
    return [x[h] * 100 + sum(math.expm1(x[j]) for j in spec) for x in data['X']]


def metrics(y, scores, ks=(50, 100, 200), min_positives=1):
    import numpy as np
    from sklearn.metrics import average_precision_score, roc_auc_score
    y, scores = np.asarray(y), np.asarray(scores, dtype=float)
    keep = ~np.isnan(scores)
    y, scores = y[keep], scores[keep]
    out = {'n': int(len(y)), 'positives': int(y.sum()), 'prevalence': round(float(y.mean()), 4) if len(y) else None}
    if y.sum() < min_positives:
        out['note'] = f'fewer than {min_positives} positives: AUC not reported'
    elif 0 < y.sum() < len(y):
        out['roc_auc'] = round(float(roc_auc_score(y, scores)), 3)
        out['pr_auc'] = round(float(average_precision_score(y, scores)), 3)
        order = np.argsort(-scores, kind='stable')
        for k in ks:
            if k <= len(y):
                out[f'precision_at_{k}'] = round(float(y[order[:k]].mean()), 3)
    return out


def explain(model, x, names, row, citations, top=4):
    """Top positive contributions (standardized value × coefficient) with the facility text behind each one.

    Only features the record actually has count as reasons (value > 0 with a positive coefficient). A positive
    contribution from something the record lacks ("not a clinic") is real but cannot be cited, so it is left out.
    """
    import numpy as np
    scaler, lr = model.named_steps['standardscaler'], model.named_steps['logisticregression']
    x = np.asarray(x, dtype=float)
    coef = lr.coef_[0]
    contrib = (x - scaler.mean_) / scaler.scale_ * coef
    reasons, cited = [], []
    for j in np.argsort(-contrib):
        if contrib[j] <= 0 or len(reasons) >= top:
            break
        name = names[j]
        if coef[j] <= 0 or x[j] <= 0 or name.endswith('_missing') or name == 'type_other':
            continue
        reasons.append(f'{feature_label(name, row, x[j])} (+{contrib[j]:.2f})')
        if name in citations:
            field, quote = citations[name]
            cited.append(f'{field}: "{quote[:160]}"')
    return reasons, cited


def leads(index, data, oof, fold_model, n=200):
    """Unlabeled facilities (Weak or no C-section evidence) ranked by held-out score, with reasons and cited text."""
    import numpy as np
    assessed = index.assessments(SERVICE)
    pool = [i for i, t in enumerate(data['tiers'])
            if t in ('weak', 'none') and not np.isnan(oof[i])
            and normalize(index.rows[i].get('facilityTypeId')) not in INCOMPATIBLE_TYPES]
    scores = np.sort(np.asarray([oof[i] for i in pool]))
    out = []
    for rank, i in enumerate(sorted(pool, key=lambda i: (-oof[i], text(index.rows[i].get('unique_id'))))[:n], 1):
        pct = float(np.searchsorted(scores, oof[i], side='right') / len(scores))
        row, loc = index.rows[i], index.locations[i]
        reasons, cited = explain(fold_model[data['regions'][i]], data['X'][i], data['names'], row, data['citations'][i])
        phones = fragments(row.get('phone_numbers'))
        a = assessed[i]
        out.append({
            'rank': rank, 'facility_id': text(row.get('unique_id')), 'name': text(row.get('name')),
            'city': text(row.get('address_city')), 'district': loc.get('district'), 'state': loc.get('state'),
            'lat': round(loc['position'][0], 5) if loc.get('position') else None,
            'lon': round(loc['position'][1], 5) if loc.get('position') else None,
            'phone': text(row.get('officialPhone')) if text(row.get('officialPhone')) not in ('', 'null') else (phones[0] if phones else None),
            'current_c_section_tier': a['tier'],
            'current_evidence_note': '; '.join(a['reasons']) or 'no C-section claim in the record',
            'lead_score': round(float(oof[i]), 4), 'score_percentile_among_unlabeled': round(pct, 4),
            'held_out_region': data['regions'][i], 'reasons': ' | '.join(reasons), 'cited_text': ' | '.join(cited),
            'use_note': USE_NOTE,
        })
    return out


def coefficients(data, C=0.3):
    """Standardized coefficients of a model fitted on every facility (for the report only)."""
    model = make_model(C).fit(data['X'], data['y'])
    coef = model.named_steps['logisticregression'].coef_[0]
    return sorted(({'feature': n, 'coefficient': round(float(c), 3)} for n, c in zip(data['names'], coef)),
                  key=lambda r: -abs(r['coefficient']))
