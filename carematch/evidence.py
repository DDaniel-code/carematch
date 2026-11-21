"""Turn one facility record into cited evidence and an evidence tier for one service.

Every evidence item is a single claim fragment copied verbatim from a named column, so any
statement we make can be traced back to the facility text.
"""
import re
from difflib import SequenceMatcher

from .services import INCOMPATIBLE_TYPES, INDIRECT, LIST_MIN_COMMAS, NEG_AFTER, NEG_BEFORE, SERVICES, SPECIALTY_NAME
from .textutil import fragments, normalize, split_camel, stable_id, text

CLAIM_FIELDS = ('procedure', 'equipment', 'capability')   # structured claim lists
TEXT_FIELDS = ('description',)                            # free prose
TIERS = ('strong', 'moderate', 'weak', 'none')

_compiled = {}


def _patterns(service):
    if service not in _compiled:
        spec = SERVICES[service]
        c = lambda ps: [re.compile(p, re.I) for p in ps]
        _compiled[service] = {
            'direct': c(spec['direct']), 'related': c(spec['related']), 'exclude': c(spec['exclude']),
            'specialties': {s.lower() for s in spec['related_specialties']},
        }
    return _compiled[service]


_INDIRECT = re.compile(INDIRECT, re.I)
_NEG_BEFORE = re.compile(NEG_BEFORE, re.I)
_NEG_AFTER = re.compile(NEG_AFTER, re.I)


def classify_fragment(fragment, service, field):
    """Return (kind, matched_text) for one fragment, or None.

    kind: direct | listed | indirect | negative | mention | related
    """
    pats = _patterns(service)
    for pat in pats['direct']:
        m = pat.search(fragment)
        if not m:
            continue
        if any(x.search(fragment) for x in pats['exclude']):
            continue
        if _NEG_BEFORE.search(fragment[max(0, m.start() - 40):m.start()]) or _NEG_AFTER.search(fragment[m.end():m.end() + 40]):
            return 'negative', m.group(0)
        if _INDIRECT.search(fragment):
            return 'indirect', m.group(0)
        if field in TEXT_FIELDS:
            return 'mention', m.group(0)
        if fragment.count(',') >= LIST_MIN_COMMAS:
            return 'listed', m.group(0)
        return 'direct', m.group(0)
    for pat in pats['related']:
        m = pat.search(fragment)
        if m and not any(x.search(fragment) for x in pats['exclude']):
            return 'related', m.group(0)
    return None


def extract_evidence(row, service):
    """All evidence items for one facility row and one service, strongest first."""
    fid = row.get('unique_id') or stable_id(row)
    items = []
    for field in CLAIM_FIELDS + TEXT_FIELDS:
        for frag in fragments(row.get(field)):
            hit = classify_fragment(frag, service, field)
            if hit:
                kind, term = hit
                items.append({'evidence_id': 'ev-' + stable_id([fid, field, frag], 12),
                              'field': field, 'text': frag, 'matched': term, 'kind': kind})
    wanted = _patterns(service)['specialties']
    listed = sorted({s for s in fragments(row.get('specialties')) if s.lower() in wanted})
    for spec in listed:
        items.append({'evidence_id': 'ev-' + stable_id([fid, 'specialties', spec], 12),
                      'field': 'specialties', 'text': split_camel(spec), 'raw': spec, 'matched': spec, 'kind': 'related'})
    order = {'direct': 0, 'listed': 1, 'negative': 2, 'indirect': 3, 'mention': 4, 'related': 5}
    field_order = {'procedure': 0, 'equipment': 1, 'capability': 2, 'description': 3, 'specialties': 4}
    items.sort(key=lambda e: (order[e['kind']], field_order[e['field']], len(e['text'])))
    return items


GENERIC_NAME_WORDS = {
    'hospital', 'hospitals', 'clinic', 'clinics', 'nursing', 'home', 'medical', 'centre', 'center', 'care', 'health',
    'healthcare', 'multispeciality', 'multispecialty', 'multi', 'super', 'speciality', 'specialty', 'the', 'and', 'of',
    'dr', 'research', 'institute', 'dental', 'eye', 'children', 'child', 'women', 'womens', 'general', 'city',
    'government', 'govt', 'district', 'civil', 'memorial', 'trust', 'charitable', 'maternity', 'surgical', 'heart',
    'kidney', 'cancer', 'diagnostic', 'diagnostics', 'pvt', 'ltd', 'private', 'limited', 'new', 'sri', 'shri', 'st',
    'fertility', 'ivf', 'dialysis', 'ortho', 'orthopaedic', 'orthopedic', 'neuro', 'skin', 'ent', 'mother', 'baby',
}
_FACILITY_NAME_RE = re.compile(
    r"\b((?:[A-Z][\w&'.-]*\.?\s+){1,5})(Hospitals?|Clinic|Nursing Home|Medical (?:Centre|Center|College)|Health ?Care)\b")


def _name_tokens(name):
    return {t for t in re.findall(r'[a-z]+', normalize(name)) if t not in GENERIC_NAME_WORDS and len(t) > 1}


def foreign_mentions(evidence, row, other_cities, canon=lambda c: c):
    """Signs that a claim describes a different facility (records that merged two sources).

    other_cities: compiled regex of well-known city names, or None; canon maps spelling variants to one key
    (Bangalore/Bengaluru). Returns a list of short reasons.
    """
    own_city = canon(normalize(row.get('address_city')))
    own = _name_tokens(row.get('name'))
    home = {normalize(row.get(k)) for k in ('address_city', 'address_stateOrRegion', 'address_line2', 'address_line3')}
    home_text = ' '.join(home)
    reasons = []
    for e in evidence:
        if e['kind'] not in ('direct', 'listed'):
            continue
        for m in _FACILITY_NAME_RE.finditer(e['text']):
            tokens = _name_tokens(m.group(0))
            similar = SequenceMatcher(None, ''.join(sorted(tokens)), ''.join(sorted(own))).ratio() >= 0.75
            if tokens and own and not tokens & own and not similar:
                reasons.append(f'a claim names another facility ("{m.group(0).strip()}")')
        if other_cities is not None:
            for m in other_cities.finditer(normalize(e['text'])):
                city = m.group(0)
                if canon(city) != own_city and city not in home_text and city not in normalize(row.get('name')):
                    reasons.append(f'a claim places the facility in {city.title()}')
    return sorted(set(reasons))


def _number(value):
    m = re.search(r'\d+(\.\d+)?', str(value or ''))
    return float(m.group(0)) if m else None


def assess(row, service, evidence=None):
    """Evidence tier for (facility, service) plus plain-language reasons and flags.

    Rules (see docs/design.md). A "claim" is a distinct sentence; the same sentence copied into two
    columns counts once. "Listed" = the service appears only inside a long department list.
      strong   - >= 2 distinct specific claims found in >= 2 columns, or >= 2 distinct specific claims plus a related
                 department/specialty
      moderate - at least one specific or listed claim
      weak     - only indirect claims (referral/outsourced/planned), prose mentions, or related departments
      none     - nothing relevant
    Caps: incompatible facility type -> weak; small clinic for an inpatient service -> moderate;
          a claim contradicted by a negative one -> moderate.
    """
    spec = SERVICES[service]
    ev = extract_evidence(row, service) if evidence is None else evidence
    specific = [e for e in ev if e['kind'] == 'direct']
    listed = [e for e in ev if e['kind'] == 'listed']
    texts = {}
    for e in specific:
        texts.setdefault(normalize(e['text']), set()).add(e['field'])
    n_specific = len(texts)
    specific_fields = set().union(*texts.values()) if texts else set()
    related = [e for e in ev if e['kind'] == 'related']
    negative = [e for e in ev if e['kind'] == 'negative']
    indirect = [e for e in ev if e['kind'] in ('indirect', 'mention')]

    reasons, flags = [], []
    if n_specific >= 2 and len(specific_fields) >= 2:
        tier = 'strong'
        reasons.append(f"{n_specific} distinct claims across {', '.join(sorted(specific_fields))}")
    elif n_specific >= 2 and (related or listed):
        tier = 'strong'
        reasons.append(f"{n_specific} distinct claims in {', '.join(sorted(specific_fields))}, plus related department evidence")
    elif n_specific >= 1:
        tier = 'moderate'
        reasons.append(f"one specific claim ({', '.join(sorted(specific_fields))})" if n_specific == 1
                       else f"{n_specific} claims in {', '.join(sorted(specific_fields))} with no corroborating department")
    elif listed:
        tier = 'moderate'
        reasons.append('named only inside a department list')
    elif indirect:
        tier = 'weak'
        kinds = sorted({'referral/outsourced/planned' if e['kind'] == 'indirect' else 'description only' for e in indirect})
        reasons.append('only ' + ' and '.join(kinds) + ' mentions')
    elif related:
        tier = 'weak'
        reasons.append('only a related department is listed, the service itself is never named')
    else:
        tier = 'none'

    def cap(level, why, flag):
        nonlocal tier
        if TIERS.index(tier) < TIERS.index(level):
            tier = level
            reasons.append(why)
        flags.append(flag)

    if negative:
        if specific or listed:
            cap('moderate', 'some text says the service is not available', 'contradictory_claims')
        else:
            reasons.append('text says the service is not available')
            flags.append('negative_claim')
            tier = 'none'
    ftype = normalize(row.get('facilityTypeId'))
    capacity = _number(row.get('capacity'))
    name_hit = re.search(SPECIALTY_NAME, text(row.get('name')), re.I)
    if name_hit and service in ('mri', 'ct_scan') and re.match(r'(lab|patholog|diagnostic)', name_hit.group(0), re.I):
        name_hit = None   # diagnostic labs can legitimately run scanners
    if ftype in INCOMPATIBLE_TYPES and tier in ('strong', 'moderate'):
        cap('weak', f"listed as a {ftype}, which is unlikely to provide {spec['label'].lower()}", 'facility_type_mismatch')
    elif name_hit and not re.search(r'\bhospital|\bmedical college|\binstitute of medical', text(row.get('name')), re.I) \
            and tier in ('strong', 'moderate'):
        cap('weak', f'the name suggests a {name_hit.group(0).lower()} specialist, unlikely to provide '
                    f"{spec['label'].lower()}", 'facility_type_mismatch')
    elif (spec['needs_inpatient'] and ftype == 'clinic' and (capacity is None or capacity < 20)
          and tier in ('strong', 'moderate')):
        cap('moderate', 'listed as a small clinic; inpatient capability unconfirmed', 'small_clinic_claim')
    if indirect and tier in ('strong', 'moderate'):
        flags.append('also_has_indirect_claims')

    return {'service': service, 'tier': tier, 'reasons': reasons, 'flags': sorted(set(flags)), 'evidence': ev}
