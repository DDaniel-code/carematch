"""Turn one facility record into cited evidence and an evidence tier for one service.

Every evidence item is a single claim fragment copied verbatim from a named column, so any
statement we make can be traced back to the facility text.
"""
import re

from .services import INCOMPATIBLE_TYPES, INDIRECT, LIST_MIN_COMMAS, NEG_AFTER, NEG_BEFORE, SERVICES
from .textutil import fragments, normalize, split_camel, stable_id

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
                      'field': 'specialties', 'text': split_camel(spec), 'matched': spec, 'kind': 'related'})
    order = {'direct': 0, 'listed': 1, 'negative': 2, 'indirect': 3, 'mention': 4, 'related': 5}
    field_order = {'procedure': 0, 'equipment': 1, 'capability': 2, 'description': 3, 'specialties': 4}
    items.sort(key=lambda e: (order[e['kind']], field_order[e['field']], len(e['text'])))
    return items


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
    if ftype in INCOMPATIBLE_TYPES and tier in ('strong', 'moderate'):
        cap('weak', f"listed as a {ftype}, which is unlikely to provide {spec['label'].lower()}", 'facility_type_mismatch')
    elif (spec['needs_inpatient'] and ftype == 'clinic' and (capacity is None or capacity < 20)
          and tier in ('strong', 'moderate')):
        cap('moderate', 'listed as a small clinic; inpatient capability unconfirmed', 'small_clinic_claim')
    if indirect and tier in ('strong', 'moderate'):
        flags.append('also_has_indirect_claims')

    return {'service': service, 'tier': tier, 'reasons': reasons, 'flags': sorted(set(flags)), 'evidence': ev}
