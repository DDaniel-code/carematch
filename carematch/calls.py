"""Who to phone first: verification call list + budgeted maximum-coverage plan (one service, e.g. c_section).

Question (district NGO coordinator): "If I can make only 10 calls this week, which facilities should I verify first,
and which PIN areas that currently lack a credible referral option would gain one for each confirmed facility?"

Definitions (shared with the map, see docs/call_plan.md):
  PIN universe   unique 6-digit PIN codes with a reliable centre: Gazetteer.pin_info(pin)['centre'], the same point the
                 app uses when a user types that PIN. 19,586 PINs, 14,008 reliable.
  covered        a PIN with at least one Strong or Moderate facility for the service within RADIUS_KM straight-line.
                 A facility whose position is uncertain covers a PIN only if every candidate position is within range
                 (the same conservative distance recommend() uses). Duplicate listings count once.
  candidate      a facility whose service evidence is still unverified (tier Weak) but that shows obstetric or surgical
                 leads, can be pinned to one branch, and is a hospital (or has >= 20 beds). Verifying a Moderate one
                 would raise confidence but adds no coverage under this metric, so Moderate/Strong are not candidates.
  gain           newly covered unique PINs, assuming the facility confirms it provides the service.
"""
import re

from .geo import city_key
from .planner import PointIndex
from .services import SERVICES, SPECIALTY_NAME
from .textutil import fragments, haversine_km, normalize, split_camel, text

RADIUS_KM = 50
MIN_BEDS = 20
BRANCH_MISMATCH_KM = 50

OBSTETRIC_LEAD = re.compile(r'\bobstetric|\bmaternity\b|\blabou?r (room|ward|suite|room)|\bdeliveries\b'
                            r'|\b(normal|vaginal|safe|institutional|painless|baby|child) ?deliver|\bdelivery (room|suite|ward)'
                            r'|\bhigh[- ]risk pregnan|\bantenatal|\bbirthing|\bgyn(a)?ecolog', re.I)
SURGICAL_LEAD = re.compile(r'\boperation theat(re|er)|\bmodular (ot|operation)|\b(ot|o\.t\.)\b|\ban(a)?esthe|\bblood bank'
                           r'|\bblood storage|\bsurgical (unit|ward|care)|\bicu\b|\bnicu\b', re.I)
OBSTETRIC_SPECIALTIES = {'gynecologyAndObstetrics', 'obstetricsAndMaternityCare', 'obstetricsAndGynaecology',
                         'obstetricsAndGynecology', 'maternalFetalMedicineOrPerinatology', 'gynecology'}


# ---- PIN universe and current coverage -------------------------------------------------------------------------------

def pin_universe(index):
    """(reliable {pin: info}, excluded [pin]) using the app's PIN centre."""
    reliable, excluded = {}, []
    for pin in sorted(index.gaz.pins):
        info = index.gaz.pin_info(pin)
        if info['reliable']:
            info = {**info, 'offices': sum(e['n_offices'] for e in index.gaz.pins[pin])}
            reliable[pin] = info
        else:
            excluded.append(pin)
    return reliable, excluded


def positions(index, i):
    loc = index.locations[i]
    return [loc['position']] + loc.get('alternatives', []) if loc['position'] else []


def reachable_pins(pin_index, pins, pts, radius_km):
    """PINs within radius of every candidate position of one facility (conservative)."""
    if not pts:
        return set()
    near = pin_index.keys_within(pts[0][0], pts[0][1], radius_km)
    return {p for p in near if all(haversine_km(pins[p]['centre'], q) <= radius_km for q in pts)}


def current_coverage(index, service='c_section', radius_km=RADIUS_KM, pins=None):
    """Covered PIN set, per-PIN nearest credible facility, and the PIN spatial index."""
    pins = pins or pin_universe(index)[0]
    pin_index = PointIndex([(i['centre'][0], i['centre'][1], p) for p, i in pins.items()])
    credible, seen_groups = [], set()
    for i, a in enumerate(index.assessments(service)):
        if a['tier'] in ('strong', 'moderate') and index.locations[i]['position']:
            credible.append(i)
    covered = {}
    for i in credible:
        g = index.dup_group[i]
        for p in reachable_pins(pin_index, pins, positions(index, i), radius_km):
            covered.setdefault(p, set()).add(g)
        seen_groups.add(g)
    fac_index = PointIndex([(index.locations[i]['position'][0], index.locations[i]['position'][1], i) for i in credible])
    nearest = {}
    tiers = index.assessments(service)
    for p, info in pins.items():
        km, i = fac_index.nearest(*info['centre'])
        nearest[p] = (round(km, 1) if km is not None else None, tiers[i]['tier'] if i is not None else None,
                      index.rows[i].get('unique_id') if i is not None else None)
    return {'covered': set(covered), 'nearest': nearest, 'pin_index': pin_index, 'pins': pins,
            'credible_facilities': len(seen_groups)}


# ---- A line: candidates ----------------------------------------------------------------------------------------------

def _branch(name):
    parts = re.split(r'\s*(?:,|\s-\s|\s–\s|\()\s*', text(name), maxsplit=1)
    return parts[1].rstrip(')').strip() if len(parts) > 1 else ''


def _phone(row):
    official = text(row.get('officialPhone'))
    if official and normalize(official) not in ('null', 'none'):
        return official
    phones = fragments(row.get('phone_numbers'))
    return phones[0] if phones else None


def _city_centres(index):
    """(city key, state) -> [(row index, position)] for every positioned facility (used to check a branch name)."""
    out = {}
    for i, r in enumerate(index.rows):
        pos = index.locations[i]['position']
        if pos:
            out.setdefault((city_key(r.get('address_city')), index.locations[i]['state']), []).append((i, pos))
    return out


def _place_far_away(index, i, place, cities):
    """True if `place` names a known town/district in the facility's own state whose centre (from other listings,
    else the PIN directory) is far from the facility's position. Same-name places in other states are ignored."""
    key = city_key(place)
    pos = index.locations[i]['position']
    state = index.locations[i]['state']
    if not key or not pos:
        return None
    others = [p for j, p in cities.get((key, state), []) if j != i]
    if len(others) < 2:
        others = []         # one other listing is not enough to define a town centre
    if others:
        lat = sorted(p[0] for p in others)[len(others) // 2]
        lon = sorted(p[1] for p in others)[len(others) // 2]
        return haversine_km(pos, (lat, lon)) > BRANCH_MISMATCH_KM
    for d in index.gaz.districts.get(normalize(place)) or []:
        if d['state'] == state:
            return haversine_km(pos, d['centre']) > BRANCH_MISMATCH_KM
    return None


def leads(row, assessment):
    """Obstetric / surgical leads with the column and verbatim text, strongest first."""
    out = []
    for e in assessment['evidence']:
        if e['field'] == 'specialties':
            continue
        if e['kind'] == 'mention':
            out.append(('service named in description', e['field'], e['text']))
        elif e['kind'] == 'indirect':
            out.append(('service mentioned with referral/partner wording', e['field'], e['text']))
    for field in ('procedure', 'capability', 'equipment', 'description'):
        for f in fragments(row.get(field)):
            if OBSTETRIC_LEAD.search(f):
                out.append(('obstetric care', field, f))
            elif SURGICAL_LEAD.search(f):
                out.append(('surgical readiness', field, f))
    specs = sorted({s for s in fragments(row.get('specialties')) if s in OBSTETRIC_SPECIALTIES})
    for s in specs:
        out.append(('obstetric specialty listed', 'specialties', s))
    seen, unique = set(), []
    for kind, field, quote in out:
        if (field, quote) not in seen:
            seen.add((field, quote))
            unique.append((kind, field, quote))
    order = {'service named in description': 0, 'service mentioned with referral/partner wording': 1,
             'obstetric care': 2, 'surgical readiness': 3, 'obstetric specialty listed': 4}
    return sorted(unique, key=lambda x: (order[x[0]], len(x[2])))


def call_questions(row, branch, service):
    where = f"{text(row.get('name'))}" + (f" — the {branch} branch" if branch else f" in {text(row.get('address_city'))}")
    if service == 'c_section':
        return [f'Am I speaking to {where}?',
                'Are caesarean sections performed at this branch, or are patients transferred to a partner hospital?',
                'At night or on a holiday, is an obstetrician and an anaesthetist available for an emergency caesarean?',
                'Is blood available on site, and which number should we call in an emergency?']
    return [f'Am I speaking to {where}?'] + SERVICES[service]['ask']


def candidates(index, service='c_section', cov=None, radius_km=RADIUS_KM):
    """(candidates, data_check) lists of dicts. Each candidate carries the uncovered PINs it would add."""
    cov = cov or current_coverage(index, service, radius_km)
    cities = _city_centres(index)
    best_by_group, data_check = {}, []
    for i, a in enumerate(index.assessments(service)):
        if a['tier'] != 'weak':
            continue
        row, loc = index.rows[i], index.locations[i]
        ftype = normalize(row.get('facilityTypeId'))
        beds = re.search(r'\d+', text(row.get('capacity')))
        beds = int(beds.group(0)) if beds and 0 < int(beds.group(0)) <= 5000 else None
        if ftype != 'hospital' and not (beds and beds >= MIN_BEDS):
            continue
        if re.search(SPECIALTY_NAME, text(row.get('name')), re.I) or re.search(
                r'\b(school|college|institute) of nursing\b|\bnursing (school|college|institute)\b', text(row.get('name')), re.I):
            continue    # ayurveda / dental / eye centres and nursing schools are not C-section candidates
        found = leads(row, a)
        text_leads = [x for x in found if x[1] != 'specialties']
        has_obstetric = any(k in ('service named in description', 'service mentioned with referral/partner wording',
                                  'obstetric care') for k, _, _ in found)
        has_surgical = any(k == 'surgical readiness' for k, _, _ in found)
        has_specialty = any(k == 'obstetric specialty listed' for k, _, _ in found)
        if not (has_obstetric or (has_specialty and has_surgical)):
            continue
        branch = _branch(row.get('name'))
        problems = []
        if not loc['position']:
            problems.append('no usable location')
        if loc['confidence'] == 'low':
            problems.append('address, PIN and map position disagree')
        if index.mixing[i]:
            problems.append('record mixes facilities: ' + '; '.join(index.mixing[i]))
        for place, label in ((branch, 'branch name'), (row.get('address_city'), 'listed city')):
            if place and _place_far_away(index, i, place, cities):
                problems.append(f'{label} "{text(place)}" is more than {BRANCH_MISMATCH_KM} km from the mapped position')
        phone = _phone(row)
        base = {
            'facility_id': row.get('unique_id'), 'name': text(row.get('name')), 'branch': branch or text(row.get('address_city')),
            'city': text(row.get('address_city')), 'state': loc['state'], 'pin': loc['pin'],
            'lat': round(loc['position'][0], 5) if loc['position'] else None,
            'lon': round(loc['position'][1], 5) if loc['position'] else None,
            'location_confidence': loc['confidence'], 'phone': phone,
            'phone_status': 'ok' if phone else 'needs_contact', 'tier': a['tier'],
            'lead_count': len(text_leads) + (1 if has_specialty else 0),
            'leads': found[:5], 'call_questions': call_questions(row, branch, service),
            'data_flags': problems, 'beds': beds, '_i': i,
        }
        if problems:
            data_check.append(base)
            continue
        base['new_pins'] = reachable_pins(cov['pin_index'], cov['pins'], positions(index, i), radius_km) - cov['covered']
        g = index.dup_group[i]
        prev = best_by_group.get(g)
        if prev is None or (base['lead_count'], base['facility_id']) > (prev['lead_count'], prev['facility_id']):
            best_by_group[g] = base
    cands = sorted(best_by_group.values(), key=lambda c: (-len(c['new_pins']), -c['lead_count'], c['facility_id']))
    return cands, sorted(data_check, key=lambda c: c['facility_id'])


# ---- B line: budgeted maximum coverage -------------------------------------------------------------------------------

def greedy_plan(cands, budget=10, exclude=()):
    """Each round pick the candidate adding the most still-uncovered PINs (ties: more leads, then facility_id).
    Stops early when no candidate adds anything. Returns ordered rows."""
    pool = sorted([c for c in cands if c['phone_status'] == 'ok' and c['facility_id'] not in set(exclude)],
                  key=lambda c: c['facility_id'])
    covered, rows = set(), []
    for rank in range(1, budget + 1):
        best, best_new, best_key = None, set(), (0, 0)
        for c in pool:            # strict '>' keeps the first facility_id on ties -> deterministic
            new = c['new_pins'] - covered
            key = (len(new), c['lead_count'])
            if key > best_key:
                best, best_new, best_key = c, new, key
        if best is None or not best_new:
            break
        covered |= best_new
        pool.remove(best)
        rows.append({'rank': rank, 'candidate': best, 'new_pins': best_new, 'marginal_gain': len(best_new),
                     'cumulative_gain': len(covered)})
    return rows


def topk_baseline(cands, k):
    """Pick the k candidates with the largest individual gain, ignoring overlap; return unique PINs actually added."""
    pool = sorted([c for c in cands if c['phone_status'] == 'ok'],
                  key=lambda c: (-len(c['new_pins']), -c['lead_count'], c['facility_id']))[:k]
    union = set().union(*(c['new_pins'] for c in pool)) if pool else set()
    return {'k': k, 'facility_ids': [c['facility_id'] for c in pool], 'sum_individual_gains': sum(len(c['new_pins']) for c in pool),
            'unique_new_pins': len(union)}


def upper_bound(cands, k):
    """No k-set can add more than the sum of the k largest individual gains."""
    gains = sorted((len(c['new_pins']) for c in cands if c['phone_status'] == 'ok'), reverse=True)
    return sum(gains[:k])
