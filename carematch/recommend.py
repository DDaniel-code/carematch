"""Service + location -> up to 3 facilities, each with quoted evidence, distance and stated uncertainty.

Ranking rule (docs/design.md):
  1. Only facilities with Strong or Moderate evidence are recommended.
  2. Distance bands from the user: 25, 75, 150, 300 km. Use the nearest band that has any recommendable facility.
  3. Inside the band: evidence tier first, then distance, then amount of evidence.
  4. If the band has only Moderate options and the next band has a Strong one, add it as "farther, stronger evidence".
  5. Nothing within 300 km -> no recommendation; show the nearest option beyond and nearby weak mentions, labelled.
Every result also lists runner-ups with the reason each was not chosen, and carries an automatic quality review.
"""
import csv
import re
import sys
from threading import Lock

from .decision import assumptions as decision_assumptions
from .decision import cost_info, drive_minutes, normalize_preferences
from .decision import score as preference_score
from .evidence import TIERS, assess, foreign_mentions, record_mixing
from .price import comparable as price_comparable
from .price import comparison_key, price_evidence, surely_cheaper
from .geo import CITY_ALIASES, Gazetteer, city_key, facility_location
from .services import SERVICES, resolve_service
from .textutil import audit_source_rows, fragments, haversine_km, normalize, source_urls, text

CONTRACT_VERSION = '1.1'
BANDS_KM = (25, 75, 150, 300)
MAX_RESULTS = 3
MAX_RUNNER_UPS = 3
DEDUP_KM = 2.0
SORT_MODES = ('default', 'nearest', 'price')
EMERGENCY_SERVICES = {'c_section', 'trauma', 'emergency', 'nicu', 'burn'}
CAN_TRAVEL_EXTRA_KM = 100            # 'can travel' looks at most 2x the nearest option's distance, or +100 km
CITY_MENTION_MIN_FACILITIES = 15     # cities this well represented are used to spot claims about another place

FLAG_TEXT = {
    'contradictory_claims': 'the record contains a statement that this service is not available',
    'small_clinic_claim': 'listed as a small clinic; inpatient capability is unconfirmed',
    'facility_type_mismatch': 'facility type does not usually offer this service',
    'also_has_indirect_claims': 'some text describes referral or outsourcing for this service',
    'coords_wrong_used_pin': 'map coordinates contradicted the PIN code and city, so the PIN code centre is used',
    'pin_inconsistent': 'the PIN code does not match the facility location',
    'location_conflict': 'the address, PIN code and map position disagree; distance uses the farthest of them — confirm the address by phone',
    'position_from_pin': 'no map coordinates; distance is from the PIN code centre',
    'position_from_city': 'no map coordinates or PIN; distance is from the city centre',
    'state_pin_mismatch': 'the state in the record does not match its PIN code',
    'possible_duplicate_listing': 'the same facility appears more than once in the data; listings were merged',
    'possible_merged_record': 'some claims may describe a different facility (the record may merge two sources)',
    'partner_claim': 'a claim says this is run with a partner organisation (not outsourced); confirm the equipment or unit is on site and working',
}
AGGREGATORS = ('practo.com', 'justdial.com', 'facebook.com', 'medindia.net', 'onefivenine.com', 'lybrate.com')


def load_csv(path):
    csv.field_size_limit(sys.maxsize)
    with open(path, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def _int(value, upper=5000):
    """First integer in the field, or None if missing or implausible (e.g. '200000' beds)."""
    m = re.search(r'\d+', text(value))
    n = int(m.group(0)) if m else None
    return n if n is not None and 0 < n <= upper else None


def _distance(o, loc):
    """Straight-line km from origin; when location signals conflict, the farthest candidate (conservative)."""
    if loc['position'] is None:
        return None
    return max(haversine_km(o, p) for p in [loc['position']] + loc.get('alternatives', []))


def _name_key(name):
    return re.sub(r'[^a-z0-9]+', ' ', normalize(name)).strip()


class CareIndex:
    """Facilities + gazetteer, with per-service assessments computed once and cached."""

    def __init__(self, facility_rows, pincode_rows):
        # Column-shifted source rows are set aside before anything is located or assessed (see audit_source_rows).
        total = len(facility_rows)
        facility_rows, self.quarantine = audit_source_rows(facility_rows)
        self.data_quality = {'input_rows': total, 'accepted_rows': len(facility_rows),
                             'quarantined_rows': len(self.quarantine)}
        self.rows = facility_rows
        self.gaz = Gazetteer(pincode_rows, facility_rows)
        self.locations = [facility_location(r, self.gaz) for r in facility_rows]
        self.by_id = {}
        for i, r in enumerate(facility_rows):
            self.by_id.setdefault(text(r.get('unique_id')), []).append(i)
        big = {k for k, opts in self.gaz.cities.items() if sum(o['n'] for o in opts) >= CITY_MENTION_MIN_FACILITIES}
        names = {n for n in big | {a for a, k in CITY_ALIASES.items() if k in big} if len(n) >= 4}
        self.city_regex = re.compile(r'\b(' + '|'.join(sorted(map(re.escape, names), key=len, reverse=True)) + r')\b') \
            if names else None
        self.mixing = [record_mixing(r, self.city_regex, city_key) for r in facility_rows]
        self.dup_group = self._duplicate_groups()
        self._assessed = {}
        self._service_locks = {service: Lock() for service in SERVICES}

    def _duplicate_groups(self):
        """Rows that are the same facility: same normalized name and (same PIN or positions within DEDUP_KM)."""
        parent = list(range(len(self.rows)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        by_name = {}
        for i, r in enumerate(self.rows):
            key = _name_key(r.get('name'))
            if key and key not in ('null', 'none'):
                by_name.setdefault(key, []).append(i)
        for idxs in by_name.values():
            for a_pos, a in enumerate(idxs):
                for b in idxs[a_pos + 1:]:
                    la, lb = self.locations[a], self.locations[b]
                    same_pin = la['pin'] and la['pin'] == lb['pin']
                    close = la['position'] and lb['position'] and haversine_km(la['position'], lb['position']) <= DEDUP_KM
                    if same_pin or close:
                        parent[find(b)] = find(a)
        groups = [find(i) for i in range(len(self.rows))]
        self._members = {}
        for i, g in enumerate(groups):
            self._members.setdefault(g, []).append(i)
        return groups

    def duplicates_of(self, i):
        return [j for j in self._members[self.dup_group[i]] if j != i]

    @classmethod
    def from_csv(cls, facilities_path='data/facilities.csv', pincodes_path='data/pincodes.csv'):
        return cls(load_csv(facilities_path), load_csv(pincodes_path))

    def assessments(self, service):
        if service in self._assessed:
            return self._assessed[service]
        # Visitors share one index. Publish a complete assessment only after the first request finishes.
        with self._service_locks[service]:
            if service in self._assessed:
                return self._assessed[service]
            out = []
            for r in self.rows:
                a = assess(r, service)
                if a['tier'] in ('strong', 'moderate'):
                    merged = foreign_mentions(a['evidence'], r, self.city_regex, city_key)
                    if merged:
                        a['flags'] = sorted(set(a['flags']) | {'possible_merged_record'})
                        a['merge_reasons'] = merged
                out.append(a)
            # Another listing of the same facility may say the service is NOT available. That listing has no tier of
            # its own and is never shown, so its statement would be lost: carry it over, keep its source record, and
            # cap the tier exactly as a contradiction inside one record does.
            negative = [[e for e in a['evidence'] if e['kind'] == 'negative'] for a in out]
            for i, a in enumerate(out):
                if a['tier'] not in ('strong', 'moderate'):
                    continue
                borrowed = [dict(e, source_facility_id=self.rows[j].get('unique_id'))
                            for j in self.duplicates_of(i) for e in negative[j]]
                if borrowed:
                    a['evidence'] = a['evidence'] + borrowed
                    a['tier'] = 'moderate'
                    a['flags'] = sorted(set(a['flags']) | {'contradictory_claims'})
                    a['reasons'] = a['reasons'] + ['another listing of this facility says the service is not available']
            self._assessed[service] = out
        return self._assessed[service]


def _card(index, i, a, dist):
    row, loc = index.rows[i], index.locations[i]
    phones = fragments(row.get('phone_numbers'))
    official = text(row.get('officialPhone'))
    website = text(row.get('officialWebsite'))
    urls = source_urls(row.get('source_urls'))
    urls = sorted(urls, key=lambda u: (any(d in u for d in AGGREGATORS), len(u)))
    quotes = [e for e in a['evidence'] if e['kind'] in ('direct', 'listed')][:3] or a['evidence'][:2]
    # A statement that the service is not available is quoted too (after the supporting quotes, never instead of them).
    supporting = [e for e in quotes if e['kind'] != 'negative']
    negatives = [e for e in a['evidence'] if e['kind'] == 'negative']
    if supporting and negatives:
        quotes = supporting[:2] + negatives[:1]
    dups = index.duplicates_of(i)
    mixing = index.mixing[i]
    flags = set(a['flags']) | set(f for f in loc['flags'] if f in FLAG_TEXT)
    if dups:
        flags.add('possible_duplicate_listing')
    if mixing:
        flags.add('possible_merged_record')
    flags = sorted(flags)
    uncertainties = [FLAG_TEXT[f] for f in flags if f in FLAG_TEXT]
    uncertainties += [r[0].upper() + r[1:] for r in sorted(set(a.get('merge_reasons', [])) | set(mixing))]
    return {
        'facility_id': row.get('unique_id'),
        'name': text(row.get('name')) or '(name missing)',
        'type': text(row.get('facilityTypeId')) or None,
        'operator': text(row.get('operatorTypeId')) or None,
        'address': ', '.join(x for x in (text(row.get(f'address_line{k}')) for k in (1, 2, 3)) if x and x != 'null'),
        'city': text(row.get('address_city')), 'state': loc['state'], 'pin': loc['pin'], 'district': loc['district'],
        'phone': official if official and official != 'null' else (phones[0] if phones else None),
        'website': website if website and website != 'null' else None,
        'beds': _int(row.get('capacity')), 'doctors': _int(row.get('numberDoctors')),
        'distance_km': max(0.1, round(dist, 1)) if dist is not None else None,
        'distance_basis': loc['basis'], 'location_confidence': loc['confidence'],
        'tier': a['tier'], 'tier_reasons': a['reasons'],
        'evidence': [{'evidence_id': e['evidence_id'], 'field': e['field'], 'quote': e['text'],
                      'verbatim': e.get('raw', e['text']), 'kind': e['kind'],
                      'source_facility_id': e.get('source_facility_id', row.get('unique_id'))} for e in quotes],
        'all_evidence_count': len(a['evidence']),
        'n_claims': len({normalize(e['text']) for e in a['evidence'] if e['kind'] in ('direct', 'listed')}),
        'flags': flags, 'uncertainties': uncertainties,
        'source_urls': urls[:3],
        'duplicate_group': index.dup_group[i],
        'ask_when_calling': SERVICES[a['service']]['ask'],
        **({'merged_ids': [index.rows[j].get('unique_id') for j in dups]} if dups else {}),
        **dict(zip(('price_info', 'price_context'), price_evidence(row, a['service']))),
    }


def _dedupe(cards):
    """Merge listings of the same facility: the same duplicate group (same normalized name and the same PIN or positions
    within DEDUP_KM, see CareIndex._duplicate_groups) or the same record id.

    Distances from the patient are never compared: two same-name branches equally far away on opposite sides of the
    patient are different facilities, however close their two distances are."""
    kept = []
    for c in cards:
        dup = next((k for k in kept if k['duplicate_group'] == c['duplicate_group']
                    or (c['facility_id'] and (c['facility_id'] == k['facility_id']
                                              or c['facility_id'] in k.get('merged_ids', [])))), None)
        if dup:
            if c['facility_id'] not in dup.setdefault('merged_ids', []):
                dup['merged_ids'].append(c['facility_id'])
            if 'possible_duplicate_listing' not in dup['flags']:
                dup['flags'].append('possible_duplicate_listing')
                dup['uncertainties'].append(FLAG_TEXT['possible_duplicate_listing'])
        else:
            kept.append(c)
    return kept


def _why_not(c, last):
    """One sentence on why a runner-up is below the last recommendation."""
    if c['tier'] == 'weak':
        return 'Not recommended: ' + (c['tier_reasons'][0] if c['tier_reasons'] else 'weak evidence') + '.'
    if TIERS.index(c['tier']) > TIERS.index(last['tier']):
        return f"{c['tier'].capitalize()} evidence ({c['tier_reasons'][0]}) versus {last['tier']} for those above."
    if c['distance_km'] is not None and last['distance_km'] is not None and c['distance_km'] > last['distance_km']:
        return f"Same {c['tier']} evidence, but farther ({c['distance_km']} km vs {last['distance_km']} km)."
    return f"Same {c['tier']} evidence and distance, but fewer supporting claims ({c['n_claims']} vs {last['n_claims']})."


URGENCY_TEXT = {'default': 'balanced', 'time_critical': 'time-critical: travel time weighs most',
                'can_travel': 'can travel: evidence and readiness weigh most'}


def _preference_rank(index, service, prefs, pool, k, origin):
    """Re-order the same recommendable pool by preference score. With cost='low_cost', facilities whose record says
    nothing about cost are listed separately (never scored as expensive)."""
    rows = {}
    base = min((drive_minutes(c['distance_km'], c.get('state'), origin.get('state'))[0] for c in pool
                if c['distance_km'] is not None), default=0.0)
    for c in pool:
        i = index.by_id.get(text(c['facility_id']), [None])[0]
        rows[c['facility_id']] = index.rows[i] if i is not None else {}
        c['preference'] = preference_score(c, rows[c['facility_id']], service, prefs, origin.get('state'), base)
        c['cost'] = c['preference']['cost']
    key = lambda c: (-c['preference']['score'], c['distance_km'] if c['distance_km'] is not None else 1e9, c['facility_id'])
    ranked = sorted(pool, key=key)
    unknown = []
    if prefs['cost'] == 'low_cost':
        documented = [c for c in ranked if c['cost']['category'] != 'unknown']
        # nothing documents cost: fall back to everyone (labelled in why_ranked) and list nothing separately
        unknown = [c for c in ranked if c['cost']['category'] == 'unknown'][:k] if documented else []
        ranked = documented or ranked
    results = ranked[:k]
    label = URGENCY_TEXT[prefs['urgency']] + ('; low cost preferred' if prefs['cost'] == 'low_cost' else '')
    for rank, c in enumerate(results, 1):
        c['rank'] = rank
        c.pop('why_not', None)
        p = c['preference']
        parts = ', '.join(f"{x['name']} {x['value']:.2f}×{x['weight']:.2f}" for x in p['components'] if x['value'] is not None)
        c['why_ranked'] = (f"#{rank} of {len(pool)} credible options by your preferences ({label}): score {p['score']:.2f} "
                           f"= {parts} (weights sum to 1).")
        if prefs['cost'] == 'low_cost' and c['cost']['category'] == 'unknown':
            c['why_ranked'] += ' No option nearby documents its cost, so cost could not be used.'
    for c in unknown:
        c.pop('rank', None)
        c['note'] = 'Cost not documented in the record (it may still be free or covered): ask when calling.'
    shown = {c['facility_id'] for c in results + unknown}
    runner_ups = []
    for c in [c for c in ranked if c['facility_id'] not in shown][:MAX_RUNNER_UPS]:
        c.pop('rank', None)
        last = results[-1]
        diffs = sorted(((lc['value'] or 0) * lc['weight'] - (cc['value'] or 0) * cc['weight'], lc['name'])
                       for lc, cc in zip(last['preference']['components'], c['preference']['components']))
        c['why_not'] = (f"Lower preference score ({c['preference']['score']:.2f} vs {last['preference']['score']:.2f}); "
                        f"biggest gap: {diffs[-1][1]}.")
        runner_ups.append(c)
    return results, runner_ups, unknown


def _tradeoff_note(top, default_first):
    """When the preference pick is farther than the default pick, say what was given up and what was gained (quoted)."""
    if top['facility_id'] == default_first['facility_id'] or top['distance_km'] is None or default_first['distance_km'] is None:
        return None
    extra_km = round(top['distance_km'] - default_first['distance_km'], 1)
    if extra_km < 1:
        return None
    gains = []
    comps = {x['name']: x for x in top['preference']['components']}
    if 'cost' in comps and comps['cost']['quote']:
        gains.append(f"its record documents affordable care: “{comps['cost']['quote']}” [{comps['cost']['field']}]")
    for s in comps['readiness'].get('signals', [])[:2]:
        gains.append(f"{s['signal']}: “{s['quote']}” [{s['field']}]")
    if TIERS.index(top['tier']) < TIERS.index(default_first['tier']):
        gains.append(f"{top['tier']} rather than {default_first['tier']} evidence")
    lost = f"{default_first['name']} is {extra_km} km nearer"
    if comps.get('cost') and (default_first.get('cost') or cost_info({})).get('category') == 'unknown':
        lost += ' (its cost is not documented, which does not mean it is expensive)'
    return f"{lost}. This option was preferred because " + ('; '.join(gains) if gains else 'its overall score was higher') + '.'


PRICE_UNIT_TEXT = {'per_session': 'per session', 'per_scan': 'per scan', 'per_day': 'per day',
                   'per_procedure': 'per procedure', 'per_month': 'per month', 'package': 'package', 'unspecified': 'unit not stated'}


def _price_text(p):
    if not p:
        return 'no price documented'
    unit = PRICE_UNIT_TEXT[p['unit']]
    if p['bound'] == 'free':
        return f'free ({unit})'
    if p['bound'] == 'exact':
        amount = f"₹{p['amount_min_inr']:,}"
    elif p['bound'] == 'range':
        amount = f"₹{p['amount_min_inr']:,}–{p['amount_max_inr']:,}"
    elif p['bound'] == 'upper_bound':
        amount = f"up to ₹{p['amount_max_inr']:,}"
    else:
        amount = f"from ₹{p['amount_min_inr']:,}"
    return f'{amount} {unit}' + (f" ({'; '.join(p['conditions'])})" if p['conditions'] else '')


def _sort_mode(index, service, mode, eligible, k, max_extra_km, bands, origin_pt):
    """'nearest' or 'price' ordering over the same credible (Strong/Moderate) candidates within the last band.

    Branch-resolved = no sign that the record mixes facilities. Location-certain = location confidence is not 'low'.
    Candidates failing either are never ranked: they are listed separately with the reason, so a distance or price is
    never claimed for a branch we cannot pin down.
    """
    pool = sorted([s for s in eligible if s[1] <= bands[-1]],
                  key=lambda s: (round(s[1], 1), s[0], text(index.rows[s[2]].get('unique_id'))))
    cards = _dedupe([_card(index, s[2], s[3], s[1]) for s in pool])
    ranked, unresolved, uncertain = [], [], []
    for c in cards:
        if 'possible_merged_record' in c['flags']:
            c['not_ranked_because'] = 'the record may mix several facilities or branches, so its distance and price cannot be attributed'
            unresolved.append(c)
        elif c['location_confidence'] == 'low':
            c['not_ranked_because'] = 'address, PIN code and map position disagree, so the straight-line distance is uncertain'
            i = index.by_id.get(text(c['facility_id']), [None])[0]
            loc = index.locations[i] if i is not None else {'position': None}
            pts = [loc['position']] + loc.get('alternatives', []) if loc['position'] else []
            if pts:
                c['distance_range_km'] = [round(min(haversine_km(origin_pt, p) for p in pts), 1), c['distance_km']]
            uncertain.append(c)
        else:
            ranked.append(c)
    # Records whose farthest plausible position is beyond the last band but whose nearest one is inside it (e.g. a
    # "Nagpur" listing mapped to Mumbai): never ranked, but shown so their claims and quoted prices are not lost.
    seen = {c['facility_id'] for c in cards}
    for s in eligible:
        if s[1] <= bands[-1] or index.locations[s[2]]['confidence'] != 'low':
            continue
        loc = index.locations[s[2]]
        near_km = min(haversine_km(origin_pt, p) for p in [loc['position']] + loc.get('alternatives', []))
        if near_km > bands[-1] or text(index.rows[s[2]].get('unique_id')) in seen:
            continue
        c = _card(index, s[2], s[3], s[1])
        c['distance_range_km'] = [round(near_km, 1), c['distance_km']]
        if 'possible_merged_record' in c['flags']:
            c['not_ranked_because'] = ('the record may mix several facilities or branches and its location is uncertain, so '
                                       'its distance and price cannot be attributed')
            unresolved.append(c)
        else:
            c['not_ranked_because'] = 'address, PIN code and map position disagree, so the straight-line distance is uncertain'
            uncertain.append(c)
    unresolved.sort(key=lambda c: c.get('distance_range_km', [c['distance_km']])[0])
    uncertain.sort(key=lambda c: c.get('distance_range_km', [c['distance_km']])[0])
    if not ranked:
        # Nothing can be pinned to one branch with a certain location: rank nothing, keep every flagged card and its reason.
        for c in unresolved + uncertain:
            c.pop('rank', None)
        reason = (f"None of the {len(unresolved) + len(uncertain)} credible options nearby can be pinned to one branch with a "
                  'certain location, so no distance or price order is claimed. They are listed with the reason; call to '
                  'confirm the address before travelling.')
        out = {'mode': mode, 'max_extra_km': max_extra_km, 'nearest_credible_km': None, 'ranked_count': 0,
               'no_ranked_reason': reason, 'branch_unresolved': unresolved[:3], 'location_uncertain': uncertain[:3],
               'band_km': None, 'safety_note': None, 'results': [], 'runner_ups': [],
               'method': (f'{mode.capitalize()} mode: Strong/Moderate evidence only (same gate as default); only branch-resolved '
                          'options with a certain location are ranked. Here none qualifies.')}
        if mode == 'price':
            out.update(price_comparison={'unit': None, 'budget_km': None, 'comparable_quotes': 0, 'ranked_by': None,
                                         'cheapest_claim': False, 'note': reason},
                       price_unknown_nearby=[], price_not_comparable=[])
        return out
    nearest_km = ranked[0]['distance_km']
    budget = round(nearest_km + max_extra_km, 1)
    out = {'mode': mode, 'max_extra_km': max_extra_km, 'nearest_credible_km': nearest_km, 'ranked_count': len(ranked)}
    safety_note = None

    if mode == 'nearest':
        order = list(ranked)
        if service in EMERGENCY_SERVICES:
            # Safety tie-break: a record that also says the service is NOT available never goes first while a clean
            # option exists within max_extra_km of it.
            clean = [c for c in order if 'contradictory_claims' not in c['flags']]
            if clean and 'contradictory_claims' in order[0]['flags'] and clean[0]['distance_km'] <= order[0]['distance_km'] + max_extra_km:
                order.remove(clean[0])
                order.insert(0, clean[0])
                clean[0]['safety_reordered'] = True
            safety_note = ('Nearest by straight line. In an emergency, call ahead with the questions on each card, or use the '
                           '108 ambulance: a nearer facility that cannot confirm the service is not the safer choice.')
        results = order[:k]
        last = results[-1]['distance_km']
        runner_ups = [dict(c, why_not=f"{round(c['distance_km'] - last, 1)} km farther than #{len(results)}") for c in order[k:k + MAX_RUNNER_UPS]]
        near = lambda c: c['distance_km'] is not None and c.get('distance_range_km', [c['distance_km']])[0] <= last + max_extra_km
        for rank, c in enumerate(results, 1):
            c['rank'] = rank
            c['why_ranked'] = (f"#{rank} by straight-line distance among {len(ranked)} credible, branch-resolved options"
                               + (' (moved up: the nearer record also says the service is not available)' if c.get('safety_reordered') else '')
                               + '.')
        strong_nearby = next((c for c in ranked if c['tier'] == 'strong' and c['distance_km'] <= results[0]['distance_km'] + max_extra_km), None)
        if service in EMERGENCY_SERVICES and results[0]['tier'] != 'strong' and strong_nearby and strong_nearby is not results[0]:
            out['stronger_option_nearby'] = {'facility_id': strong_nearby['facility_id'], 'name': strong_nearby['name'],
                                             'distance_km': strong_nearby['distance_km'],
                                             'note': 'Strong evidence, within max_extra_km of the nearest option'}
        out.update(method=('Nearest mode: Strong/Moderate evidence only (same gate as default); credible branch-resolved '
                           'options ordered by conservative straight-line distance (farthest plausible position when a '
                           'location is uncertain). Unresolved branches and uncertain locations are listed, not ranked.'),
                   branch_unresolved=[c for c in unresolved if near(c)][:3],
                   location_uncertain=[c for c in uncertain if near(c)][:3])
    else:
        in_budget = [c for c in ranked if c['distance_km'] <= budget]
        # Like-for-like: same service, same stated unit AND the same conditions (eligibility, scheme, inclusions, ...).
        # A concessional BPL rate and an ordinary rate share a unit but not who can get them, so they are never ranked
        # against each other.
        groups = {}
        for c in in_budget:
            p = c['price_info']
            if p and p['bound'] != 'free' and p['unit'] != 'unspecified':
                groups.setdefault(comparison_key(p), []).append(c)
        key = max(groups, key=lambda g: (len(groups[g]), -groups[g][0]['distance_km'])) if groups else None
        comparable = [c for c in groups.get(key, [])
                      if all(price_comparable(c['price_info'], d['price_info']) for d in groups.get(key, []))]
        unit, conditions = key[:2] if key else (None, ())
        pinned = None
        if service in EMERGENCY_SERVICES:
            # Urgent service: the nearest safe option (certain location, no "not available" statement) stays first;
            # price only orders the options after it.
            pinned = next((c for c in in_budget if 'contradictory_claims' not in c['flags']), None)
            safety_note = ('Urgent service: the nearest safe option is kept first; price only orders the options after it. '
                           'In an emergency, call ahead with the questions on each card, or use the 108 ambulance.')
        inf = float('inf')
        price_key = lambda c: (c['price_info']['amount_max_inr'] if c['price_info']['amount_max_inr'] is not None else inf,
                               c['price_info']['amount_min_inr'] or 0, c['distance_km'])
        cheapest = False
        if len(comparable) >= 2:
            comparable.sort(key=price_key)
            top = comparable[0]
            cheapest = all(surely_cheaper(top['price_info'], c['price_info']) for c in comparable[1:])
            ordered = comparable
            ranked_by = 'price'
            cond_text = f" under the same conditions ({'; '.join(conditions)})" if conditions else ''
            if cheapest:
                note = (f"{top['name']} documents a lower {PRICE_UNIT_TEXT[unit]} price than every other like-for-like quote "
                        f"within {budget} km{cond_text}.")
            else:
                note = (f"Ordered by documented {PRICE_UNIT_TEXT[unit]} price (upper amount first) among {len(comparable)} "
                        f"like-for-like quotes{cond_text}. No option is called the cheapest: the documented ranges overlap.")
        else:
            ordered = in_budget
            ranked_by = 'distance'
            note = (f"{len(comparable)} like-for-like documented price(s) within {budget} km (same service, unit and "
                    'conditions): prices cannot be ranked, so options are shown nearest first with every documented price '
                    'labelled on its card.')
        if pinned is not None:
            ordered = [pinned] + [c for c in ordered if c is not pinned]
            pinned['safety_pinned'] = True
        results = ordered[:k]
        shown = {c['facility_id'] for c in results}
        for rank, c in enumerate(results, 1):
            c['rank'] = rank
            if c.get('safety_pinned'):
                c['why_ranked'] = (f"#{rank}: nearest safe option for an urgent service ({c['distance_km']} km), kept first "
                                   f"whatever its price ({_price_text(c['price_info'])}).")
            elif ranked_by == 'price':
                c['why_ranked'] = f"#{rank}: {_price_text(c['price_info'])}, {c['distance_km']} km"
            else:
                c['why_ranked'] = f"#{rank} by distance within {budget} km ({_price_text(c['price_info'])})."
        last = results[-1]
        runner_ups = [dict(c, why_not=(f"documented price {_price_text(c['price_info'])} is not lower" if ranked_by == 'price'
                                       else f"{round(c['distance_km'] - last['distance_km'], 1)} km farther"))
                      for c in ordered[k:]][:MAX_RUNNER_UPS]

        def why_not_comparable(c):
            p = c['price_info']
            if p['bound'] == 'free':
                return 'free only with conditions: ' + ('; '.join(p['conditions']) or 'none stated')
            if p['unit'] == 'unspecified':
                return 'unit not stated'
            if p['unit'] != unit:
                return f"different unit ({PRICE_UNIT_TEXT[p['unit']]})"
            return ('different eligibility or conditions: ' + ('; '.join(p['conditions']) or 'no conditions stated')
                    + ' vs ' + ('; '.join(conditions) or 'no conditions stated'))

        within = lambda c: c['distance_km'] is not None and c.get('distance_range_km', [c['distance_km']])[0] <= budget
        out.update(
            method=(f'Price mode: Strong/Moderate evidence only (same gate as default); among credible branch-resolved options '
                    f'within {max_extra_km} km of the nearest one ({budget} km), documented patient prices for this service are '
                    'compared only when they state the same unit and the same conditions (eligibility, scheme, inclusions); '
                    'upper/lower bounds are kept, never filled in. Urgent services keep the nearest safe option first. '
                    'Options without a comparable price stay visible.'),
            price_comparison={'unit': unit, 'conditions': list(conditions), 'budget_km': budget,
                              'comparable_quotes': len(comparable), 'ranked_by': ranked_by, 'cheapest_claim': cheapest,
                              'safety_pinned': pinned['facility_id'] if pinned is not None else None, 'note': note},
            price_unknown_nearby=[c for c in in_budget if not c['price_info'] and c['facility_id'] not in shown][:k],
            price_not_comparable=[dict(c, not_comparable_because=why_not_comparable(c))
                                  for c in in_budget if c['price_info'] and c not in comparable
                                  and c['facility_id'] not in shown][:k],
            branch_unresolved=[c for c in unresolved if within(c)][:3],
            location_uncertain=[c for c in uncertain if within(c)][:3])
        for c in results + runner_ups:      # label every shown quote: compared like-for-like, or why not
            if c['price_info']:
                c['price_comparable'] = c in comparable or any(c['facility_id'] == x['facility_id'] for x in comparable)
                if not c['price_comparable']:
                    c['not_comparable_because'] = why_not_comparable(c)
    for c in runner_ups + out.get('branch_unresolved', []) + out.get('location_uncertain', []) + \
            out.get('price_unknown_nearby', []) + out.get('price_not_comparable', []):
        c.pop('rank', None)
    far = max(c['distance_km'] for c in results)
    out['band_km'] = next((b for b in bands if far <= b), bands[-1])
    out['safety_note'] = safety_note
    out['results'], out['runner_ups'] = results, runner_ups
    return out


def _apply_variant(a, strong_min_claims):
    """Sensitivity variant: require more distinct claims for Strong."""
    if strong_min_claims and a['tier'] == 'strong':
        n = len({normalize(e['text']) for e in a['evidence'] if e['kind'] == 'direct'})
        if n < strong_min_claims:
            return {**a, 'tier': 'moderate', 'reasons': a['reasons'] + [f'fewer than {strong_min_claims} distinct claims']}
    return a


def recommend(index, service_text, location_text, k=MAX_RESULTS, bands=BANDS_KM, strong_min_claims=None, review=True,
              preferences=None, sort_mode='default', max_extra_km=25):
    """preferences: optional {'urgency': 'default'|'time_critical'|'can_travel', 'cost': 'any'|'low_cost'}.
    sort_mode: 'default' (evidence, then distance), 'nearest' (straight-line distance among credible, branch-resolved
    options) or 'price' (documented comparable service prices within max_extra_km of the nearest credible option).
    Without preferences and with sort_mode='default' the output is exactly the evidence-then-distance ranking."""
    prefs = normalize_preferences(preferences)
    if sort_mode not in SORT_MODES:
        raise ValueError(f'sort_mode must be one of {SORT_MODES}')
    if sort_mode != 'default' and prefs['applied']:
        raise ValueError('use either preferences or sort_mode, not both')
    if isinstance(max_extra_km, bool) or not isinstance(max_extra_km, (int, float)) or not 0 <= max_extra_km <= 300:
        raise ValueError('max_extra_km must be a number between 0 and 300')
    service = resolve_service(service_text)
    if not service:
        return {'error': f'Unknown service "{service_text}". Choose one of: '
                         + ', '.join(s['label'] for s in SERVICES.values())}
    origin = index.gaz.resolve(location_text)
    if 'error' in origin:
        return {k: origin[k] for k in ('error', 'suggestions') if k in origin}
    o = (origin['lat'], origin['lon'])

    scored = []          # (tier_rank, distance, i, assessment)
    no_distance = 0
    for i, a in enumerate(index.assessments(service)):
        if a['tier'] == 'none':
            continue
        a = _apply_variant(a, strong_min_claims)
        dist = _distance(o, index.locations[i])
        if dist is None:
            no_distance += a['tier'] in ('strong', 'moderate')
            continue
        if a['tier'] == 'strong' and index.locations[i]['confidence'] == 'low':
            a = {**a, 'tier': 'moderate', 'reasons': a['reasons'] + ['location data conflicts, so treated as moderate'],
                 'flags': sorted(set(a['flags']) | {'location_conflict'})}
        if a['tier'] == 'strong' and a.get('merge_reasons') and all(
                foreign_mentions([e], index.rows[i], index.city_regex, city_key)
                for e in a['evidence'] if e['kind'] == 'direct'):
            a = {**a, 'tier': 'moderate', 'reasons': a['reasons'] + ['every claim may describe another facility']}
        scored.append((TIERS.index(a['tier']), dist, i, a))

    eligible = [s for s in scored if s[0] <= 1]
    # Amount of evidence is the last tie-break; a "not available" statement carried over from another listing is not
    # counted, so a contradiction can never move a facility up.
    own = lambda a: sum(1 for e in a['evidence'] if 'source_facility_id' not in e)
    order = lambda s: (s[0], round(s[1], 1), -own(s[3]), text(index.rows[s[2]].get('unique_id')))
    counts = {b: {t: sum(1 for s in scored if s[1] <= b and TIERS[s[0]] == t) for t in ('strong', 'moderate', 'weak')}
              for b in bands}

    # An approximate location (a PIN known only to its area, +-25 km, or a whole district) cannot support a
    # 25 km answer: start at the first band at least twice the location's uncertainty. City names are exempt:
    # their "precision" is the city's size, and a city user is somewhere inside it.
    coarse = origin['kind'] in ('pin', 'pin_area', 'district')
    start = [b for b in bands if not coarse or b >= 2 * origin['precision_km']] or [bands[-1]]
    if start[0] != bands[0]:
        origin = {**origin, 'notes': origin['notes'] + [
            f"Your location is only known to about ±{origin['precision_km']:g} km, so the search starts at {start[0]} km."]}

    chosen_band, results, extra, runner_ups = None, [], None, []
    found = []          # recommendable cards, nearest band first; each remembers the band it was found in
    for b in start:
        in_band = sorted([s for s in scored if s[1] <= b], key=order)
        if not any(s[0] <= 1 for s in in_band):
            continue
        chosen_band = b
        cards = _dedupe([_card(index, s[2], s[3], s[1]) for s in in_band if s[0] <= 1])
        known = {c['facility_id'] for c in found} | {m for c in found for m in c.get('merged_ids', [])}
        for c in cards:
            if c['facility_id'] not in known and not set(c.get('merged_ids', [])) & known:
                c['found_within_km'] = b
                found.append(c)
        found = _dedupe(found)
        if coarse and len(found) < k and b != bands[-1]:
            continue   # approximate location: widen until there are k options to compare (or the last band)
        if coarse and b != start[0] and len({c['found_within_km'] for c in found[:k]}) > 1:
            origin = {**origin, 'notes': origin['notes'] + [
                f'Fewer than {k} credible options nearby; widened the search to {b} km because the location is approximate. '
                'Nearer options are listed first.']}
        results = found[:k]
        weak = _dedupe([_card(index, s[2], s[3], s[1]) for s in in_band if s[0] == 2])
        shown = {_name_key(c['name']) for c in results}
        pool = found[k:] + [w for w in weak if _name_key(w['name']) not in shown]
        for c in pool[:MAX_RUNNER_UPS]:
            c['why_not'] = _why_not(c, results[-1])
            runner_ups.append(c)
        if all(c['tier'] != 'strong' for c in results):
            nxt = bands[bands.index(b) + 1] if b != bands[-1] else None
            stronger = sorted([s for s in eligible if s[0] == 0 and s[1] > b and (nxt is None or s[1] <= nxt)],
                              key=order)
            if stronger:
                extra = _card(index, stronger[0][2], stronger[0][3], stronger[0][1])
                extra['note'] = 'Farther away, but stronger evidence than the options above.'
        break

    beyond, weak_nearby = None, []
    if not results:
        far = sorted(eligible, key=lambda s: (round(s[1], 1), s[0]))
        if far:
            beyond = _card(index, far[0][2], far[0][3], far[0][1])
            beyond['note'] = f'Nearest facility with credible evidence, beyond {bands[-1]} km.'
        weak = sorted([s for s in scored if s[0] == 2 and s[1] <= bands[1]], key=order)[:3]
        weak_nearby = [_card(index, s[2], s[3], s[1]) for s in weak]

    n_in_band = len([s for s in eligible if chosen_band and s[1] <= chosen_band])
    for rank, c in enumerate(results, 1):
        c['rank'] = rank
        if c.get('found_within_km', chosen_band) != chosen_band:
            c['why_ranked'] = (f"#{rank}: found within {c['found_within_km']} km, the nearest search radius with credible "
                               f"evidence; listed before options found only after widening to {chosen_band} km.")
        else:
            c['why_ranked'] = (f"#{rank} of {n_in_band} facilities with credible evidence within {chosen_band} km; "
                               f"ordered by evidence strength, then distance.")

    default_ids = [c['facility_id'] for c in results]
    cost_unknown, tradeoff = [], None
    if prefs['applied'] and results:
        pool = list(found)
        if prefs['urgency'] == 'can_travel' and chosen_band != bands[-1]:
            nxt = bands[bands.index(chosen_band) + 1]
            nearest = min(c['distance_km'] for c in pool if c['distance_km'] is not None)
            cap = min(nxt, max(2 * nearest, nearest + CAN_TRAVEL_EXTRA_KM))   # further, but within reason
            known = {c['facility_id'] for c in pool} | {m for c in pool for m in c.get('merged_ids', [])}
            for s in sorted([s for s in eligible if chosen_band < s[1] <= cap], key=order):
                c = _card(index, s[2], s[3], s[1])
                if c['facility_id'] not in known and not set(c.get('merged_ids', [])) & known:
                    c['found_within_km'] = nxt
                    pool.append(c)
            pool = _dedupe(pool)
        default_first = next((c for c in found if c['facility_id'] == default_ids[0]), None) if default_ids else None
        results, runner_ups, cost_unknown = _preference_rank(index, service, prefs, pool, k, origin)
        if extra and extra['facility_id'] in {c['facility_id'] for c in results + cost_unknown}:
            extra = None
        tradeoff = _tradeoff_note(results[0], default_first) if results and default_first else None

    mode = None
    if sort_mode != 'default' and results:
        mode = _sort_mode(index, service, sort_mode, eligible, k, max_extra_km, bands, o)
        results, runner_ups, extra = mode.pop('results'), mode.pop('runner_ups'), None
        chosen_band, n_in_band = mode['band_km'], mode['ranked_count']

    first_ask = SERVICES[service]['ask'][0]
    if mode and not results and mode.get('no_ranked_reason'):
        advice = mode['no_ranked_reason']
    elif not results:
        advice = ('No facility with credible evidence within reach. Call the nearest option shown before travelling, '
                  'and check with the district hospital or 108 ambulance service.')
    elif n_in_band <= 2 or chosen_band >= 75:
        advice = (f'Few alternatives within reach ({n_in_band} within {chosen_band} km): call the first option before '
                  f'setting off and ask: "{first_ask}" Keep the second option ready in case it cannot confirm.')
    else:
        advice = (f'{n_in_band} facilities with credible evidence within {chosen_band} km. Call the first option; '
                  f'if it cannot confirm, move to the next one.')

    result = {
        'contract_version': CONTRACT_VERSION,
        'data_quality': dict(index.data_quality),
        'service': service, 'service_label': SERVICES[service]['label'], 'service_scope': SERVICES[service]['scope'],
        'origin': origin, 'band_km': chosen_band, 'action_advice': advice, 'results': results, 'runner_ups': runner_ups,
        'farther_stronger': extra, 'nearest_beyond': beyond, 'weak_nearby': weak_nearby,
        'considered': {'by_band': counts, 'recommendable_without_location': no_distance},
        'parameters': {'bands_km': list(bands), 'max_results': k, 'strong_min_claims': strong_min_claims},
        'preferences': prefs, 'sort_mode': sort_mode,
        **({'sort': mode} if mode else {}),
        **({'preference_model': decision_assumptions(prefs), 'default_order_ids': default_ids,
            'cost_unknown_options': cost_unknown, 'tradeoff_note': tradeoff} if prefs['applied'] else {}),
        'method': (mode['method'] if mode else
                   'Strong/Moderate evidence only; nearest distance band (' + '/'.join(map(str, bands)) + ' km) that has '
                   'any; within it, stronger evidence first, then shorter straight-line distance.'),
        'disclaimer': ('Based on public web listings, not verified by the facility. Availability today is unknown: '
                       'call before travelling. Distances are straight-line, not road travel time.'),
    }
    if review:
        from .review import review as run_review
        result['review'] = run_review(index, result)
    return result
