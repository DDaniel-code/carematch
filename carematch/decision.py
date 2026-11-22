"""Optional preference ranking: re-order the credible options by what the user says matters.

The evidence gate, the search radius and the honest "nothing within 300 km" answer are unchanged: this module only
re-orders facilities that recommend() already considers recommendable (Strong or Moderate).

Preferences
  urgency  'default'        no preference model (recommend() keeps its evidence-then-distance order)
           'time_critical'  every minute on the road counts (e.g. bleeding in labour, road accident)
           'can_travel'     the patient can travel further for stronger evidence and better readiness
  cost     'any'            cost is shown but does not change the order
           'low_cost'       prefer facilities whose record documents free / government-scheme / insured care

Score = weighted sum of components in [0, 1]. Every component carries a plain reason and, where it rests on the record,
the verbatim quote and its column. The components are ranking weights built from stated assumptions; none of them is a
probability of being treated or of survival, and the app never presents them that way.
"""
import math
import re

from .price import NOT_MONEY_FREE
from .textutil import fragments, normalize, text

URGENCY = ('default', 'time_critical', 'can_travel')
COST = ('any', 'low_cost')

# Assumptions used to turn straight-line km into an estimated drive time (shown to the user with every estimate).
ROAD_FACTOR = 1.4                     # road distance ~ 1.4 x straight line
SPEED_KMH = {'plains': 40.0, 'hills': 25.0}
HILL_STATES = {'Jammu And Kashmir', 'Ladakh', 'Himachal Pradesh', 'Uttarakhand', 'Sikkim', 'Arunachal Pradesh',
               'Meghalaya', 'Nagaland', 'Manipur', 'Mizoram'}
# How quickly the travel component falls with EXTRA drive time compared with the nearest credible option:
# weight = exp(-extra_minutes / tau). Relative, so the nearest option always scores 1.0 even in remote districts
# where every option is hours away (an absolute decay would flatten to zero there and stop discriminating).
TAU_MINUTES = {'time_critical': 45.0, 'default': 120.0, 'can_travel': 480.0}
# Where even the nearest option is hours away, an extra hour matters relatively less than in a city, and a fixed tau
# would flatten every option to ~0. The decay scale therefore grows with the nearest option's drive time.
TAU_SCALE = {'time_critical': 0.5, 'default': 1.0, 'can_travel': 2.0}

WEIGHTS = {   # evidence, travel, readiness (cost added separately when requested)
    'time_critical': {'evidence': 0.35, 'travel': 0.45, 'readiness': 0.20},
    'default':       {'evidence': 0.45, 'travel': 0.30, 'readiness': 0.25},
    'can_travel':    {'evidence': 0.55, 'travel': 0.10, 'readiness': 0.35},
}
COST_WEIGHT = 0.30
TIER_VALUE = {'strong': 1.0, 'moderate': 0.6}

READINESS = {
    'c_section': ['anaesthesia', 'blood', 'theatre', 'round_the_clock', 'newborn_care'],
    'trauma': ['icu', 'blood', 'ct', 'round_the_clock', 'ambulance', 'neuro_ortho'],
    'emergency': ['round_the_clock', 'ambulance', 'icu'],
    'nicu': ['round_the_clock', 'ventilation', 'paediatrician'],
    'burn': ['icu', 'plastic_surgery', 'round_the_clock'],
    'dialysis': ['nephrologist', 'round_the_clock', 'machines'],
    'cardiac_surgery': ['icu', 'cath_lab', 'blood'],
    'mri': ['round_the_clock', 'scanner_spec'],
    'ct_scan': ['round_the_clock', 'scanner_spec'],
}
SIGNALS = {
    'anaesthesia': (r'\ban(a)?esthe', 'anaesthesia'),
    'blood': (r'\bblood bank|\bblood storage|\bblood (component|transfusion)', 'blood bank / storage'),
    'theatre': (r'\boperation theat(re|er)|\bmodular (ot|operation)|\boperating room', 'operation theatre'),
    'round_the_clock': (r'\b24\s*[x×/*]\s*7\b|\b24 hours\b|\bround[- ]the[- ]clock|\baround the clock', '24x7 service'),
    'newborn_care': (r'\bnicu\b|\bneonatal|\bnewborn care|\bsncu\b', 'newborn care'),
    'icu': (r'\bicu\b|\bintensive care|\bccu\b|\bcritical care', 'ICU / critical care'),
    'ct': (r'\bct\b|\bcomputed tomography', 'CT scanner'),
    'ambulance': (r'\bambulance', 'ambulance'),
    'neuro_ortho': (r'\bneurosurg|\borthopa?edic surg', 'neuro / orthopaedic surgery'),
    'ventilation': (r'\bventilat|\bcpap\b|\bhfov\b', 'newborn ventilation / CPAP'),
    'paediatrician': (r'\bpa?ediatrician|\bneonatologist', 'paediatrician / neonatologist'),
    'plastic_surgery': (r'\bplastic surg|\bskin graft', 'plastic surgery'),
    'nephrologist': (r'\bnephrologist', 'nephrologist'),
    'machines': (r'\b\d+\s*(bed(ded)?\s*)?(dialysis|haemodialysis|hemodialysis) (machines|units|beds)|\b(machines|units)\b.{0,20}dialysis',
                 'number of dialysis machines'),
    'cath_lab': (r'\bcath(eteri[sz]ation)? ?lab', 'cath lab'),
    'scanner_spec': (r'\b\d(\.\d)?\s*t(esla)?\b|\b\d+[- ]slice', 'scanner specification'),
}
COVERED_TEXT = re.compile(r'\bayushman|\bpm-?jay\b|\bpmjay\b|\bjan arogya|\baarogyasri|\barogyasri|\bmjpjay|\bphule jan'
                          r'|\bcmchis\b|\bchiranjeevi|\bswasthya sathi|\bbiju swasthya|\besic?\b|\bcghs\b|\bemployees.? state insurance'
                          r'|\bfree of cost\b|\bfree (treatment|services?|consultation|surgery|delivery|dialysis)|\bcharitable'
                          r'|\bsubsidi[sz]ed|\bno cost\b|\bnominal (fee|charge)', re.I)
INSURED_TEXT = re.compile(r'\bcashless|\btpa\b|\binsurance', re.I)
# A 24x7 pharmacy or laboratory is not clinical readiness for the service.
NON_CLINICAL = re.compile(r'\blab\b|\blaborator|\bpharmac|\bchemist|\bcanteen|\bcafeteria|\bparking|\batm\b|\bcollection centre'
                          r'|\bmicrobiolog|\bpatholog|\bblood test|\bhome (sample|collection)', re.I)
NEGATED = re.compile(r'\b(no|not|without|isn.?t|doesn.?t|does not|non)\W+(\w+\W+){0,3}$', re.I)
CLAIM_FIELDS = ('procedure', 'equipment', 'capability', 'description')


def normalize_preferences(prefs):
    prefs = prefs or {}
    urgency = prefs.get('urgency') or 'default'
    cost = prefs.get('cost') or 'any'
    if urgency not in URGENCY:
        raise ValueError(f'urgency must be one of {URGENCY}')
    if cost not in COST:
        raise ValueError(f'cost must be one of {COST}')
    return {'urgency': urgency, 'cost': cost, 'applied': urgency != 'default' or cost != 'any'}


def _find(row, pattern, clinical_only=False):
    """First fragment (column, verbatim text) matching pattern without a nearby negation."""
    rx = re.compile(pattern, re.I) if isinstance(pattern, str) else pattern
    for field in CLAIM_FIELDS:
        for frag in fragments(row.get(field)):
            searchable = NOT_MONEY_FREE.sub(lambda match: " " * len(match[0]), frag) if rx is COVERED_TEXT else frag
            m = rx.search(searchable)
            if m and not NEGATED.search(frag[max(0, m.start() - 30):m.start()]) \
                    and not (clinical_only and NON_CLINICAL.search(frag)):
                return field, frag
    return None


def cost_info(row):
    """Documented affordability: covered (public / scheme / charitable), insured (cashless / insurance), or unknown."""
    op = normalize(row.get('operatorTypeId'))
    if op in ('public', 'government'):
        return {'category': 'covered', 'value': 1.0, 'reason': 'operator listed as public', 'field': 'operatorTypeId',
                'quote': text(row.get('operatorTypeId'))}
    hit = _find(row, COVERED_TEXT)
    if hit:
        return {'category': 'covered', 'value': 1.0, 'reason': 'record mentions free care or a government scheme',
                'field': hit[0], 'quote': hit[1]}
    hit = _find(row, INSURED_TEXT)
    if hit:
        return {'category': 'insured', 'value': 0.6, 'reason': 'record mentions cashless / insurance payment',
                'field': hit[0], 'quote': hit[1]}
    return {'category': 'unknown', 'value': None, 'reason': 'the record says nothing about cost or payment schemes',
            'field': None, 'quote': None}


def readiness(row, service):
    signals = READINESS.get(service, [])
    found, missing = [], []
    for key in signals:
        pattern, label = SIGNALS[key]
        hit = _find(row, pattern, clinical_only=True)
        if hit:
            found.append({'signal': label, 'field': hit[0], 'quote': hit[1]})
        else:
            missing.append(label)
    return {'value': len(found) / len(signals) if signals else 0.0, 'found': found, 'missing': missing}


def drive_minutes(km, state, origin_state=None):
    hills = state in HILL_STATES or origin_state in HILL_STATES
    speed = SPEED_KMH['hills'] if hills else SPEED_KMH['plains']
    return km * ROAD_FACTOR / speed * 60.0, speed


def score(card, row, service, prefs, origin_state=None, baseline_minutes=0.0):
    """Preference score with itemised components for one result card."""
    urgency = prefs['urgency']
    weights = dict(WEIGHTS[urgency])
    cost = cost_info(row)
    use_cost = prefs['cost'] == 'low_cost' and cost['value'] is not None
    if prefs['cost'] == 'low_cost':
        weights = {k: v * (1 - COST_WEIGHT) for k, v in weights.items()}
        weights['cost'] = COST_WEIGHT
    ev = card['evidence'][0] if card['evidence'] else None
    evidence_value = TIER_VALUE.get(card['tier'], 0.0)
    minutes, speed = drive_minutes(card['distance_km'] or 0.0, card.get('state'), origin_state)
    extra = max(0.0, minutes - baseline_minutes)
    tau = max(TAU_MINUTES[urgency], TAU_SCALE[urgency] * baseline_minutes)
    travel_value = math.exp(-extra / tau)
    ready = readiness(row, service)
    comps = [
        {'name': 'evidence', 'value': round(evidence_value, 3), 'weight': round(weights['evidence'], 3),
         'reason': f"{card['tier']} evidence: {card['tier_reasons'][0] if card['tier_reasons'] else ''}",
         'field': ev['field'] if ev else None, 'quote': ev['quote'] if ev else None},
        {'name': 'travel', 'value': round(travel_value, 3), 'weight': round(weights['travel'], 3),
         'reason': (f"{card['distance_km']} km straight-line ≈ {minutes:.0f} min by road"
                    + (f", {extra:.0f} min more than the nearest credible option" if extra >= 1 else ', the nearest credible option')
                    + f" (assumes road ≈ {ROAD_FACTOR}× straight line at {speed:.0f} km/h; an estimate, not a route)"),
         'field': None, 'quote': None},
        {'name': 'readiness', 'value': round(ready['value'], 3), 'weight': round(weights['readiness'], 3),
         'reason': (f"{len(ready['found'])} of {len(ready['found']) + len(ready['missing'])} readiness signals in the record"
                    + (f"; not mentioned: {', '.join(ready['missing'])}" if ready['missing'] else '')),
         'signals': ready['found']},
    ]
    if prefs['cost'] == 'low_cost':
        comps.append({'name': 'cost', 'value': cost['value'], 'weight': COST_WEIGHT if use_cost else 0.0,
                      'reason': cost['reason'], 'field': cost['field'], 'quote': cost['quote']})
    total_w = sum(c['weight'] for c in comps)
    total = sum(c['value'] * c['weight'] for c in comps if c['value'] is not None) / total_w if total_w else 0.0
    return {'score': round(total, 4), 'components': comps, 'cost': cost, 'drive_minutes_estimate': round(minutes),
            'note': 'A ranking weight built from stated assumptions, not a probability of treatment or survival.'}


def assumptions(prefs):
    return {
        'urgency': prefs['urgency'], 'cost': prefs['cost'],
        'weights': {**WEIGHTS[prefs['urgency']], **({'cost': COST_WEIGHT} if prefs['cost'] == 'low_cost' else {})},
        'travel': f'drive time = km × {ROAD_FACTOR} / speed ({SPEED_KMH["plains"]:.0f} km/h; {SPEED_KMH["hills"]:.0f} km/h in hill '
                  f'states); travel weight = exp(-extra minutes vs the nearest credible option / tau), '
                  f'tau = max({TAU_MINUTES[prefs["urgency"]]:.0f} min, {TAU_SCALE[prefs["urgency"]]:g} × nearest option drive time)',
        'evidence': 'Strong = 1.0, Moderate = 0.6',
        'readiness': 'share of service-specific readiness signals mentioned in the record (24x7, blood bank, anaesthesia, ...)',
        'cost': 'covered (public, government scheme, free/charitable) = 1.0; cashless/insurance = 0.6; '
                'not documented = listed separately, never scored as expensive',
        'not_a_probability': 'Scores order the options; they are not chances of being treated or of survival.',
    }
