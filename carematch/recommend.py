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

from .evidence import TIERS, assess, foreign_mentions, record_mixing
from .geo import CITY_ALIASES, Gazetteer, city_key, facility_location
from .services import SERVICES, resolve_service
from .textutil import fragments, haversine_km, normalize, source_urls, text

CONTRACT_VERSION = '1.1'
BANDS_KM = (25, 75, 150, 300)
MAX_RESULTS = 3
MAX_RUNNER_UPS = 3
DEDUP_KM = 2.0
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
        if service not in self._assessed:
            out = []
            for r in self.rows:
                a = assess(r, service)
                if a['tier'] in ('strong', 'moderate'):
                    merged = foreign_mentions(a['evidence'], r, self.city_regex, city_key)
                    if merged:
                        a['flags'] = sorted(set(a['flags']) | {'possible_merged_record'})
                        a['merge_reasons'] = merged
                out.append(a)
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
                      'verbatim': e.get('raw', e['text']), 'kind': e['kind']} for e in quotes],
        'all_evidence_count': len(a['evidence']),
        'n_claims': len({normalize(e['text']) for e in a['evidence'] if e['kind'] in ('direct', 'listed')}),
        'flags': flags, 'uncertainties': uncertainties,
        'source_urls': urls[:3],
        'ask_when_calling': SERVICES[a['service']]['ask'],
        **({'merged_ids': [index.rows[j].get('unique_id') for j in dups]} if dups else {}),
    }


def _dedupe(cards):
    """Merge listings with the same normalized name within DEDUP_KM (or same name and no distance)."""
    kept = []
    for c in cards:
        dup = next((k for k in kept if c['facility_id'] in k.get('merged_ids', [])
                    or (_name_key(k['name']) == _name_key(c['name'])
                        and (k['distance_km'] is None or c['distance_km'] is None
                             or abs(k['distance_km'] - c['distance_km']) <= DEDUP_KM))), None)
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


def _apply_variant(a, strong_min_claims):
    """Sensitivity variant: require more distinct claims for Strong."""
    if strong_min_claims and a['tier'] == 'strong':
        n = len({normalize(e['text']) for e in a['evidence'] if e['kind'] == 'direct'})
        if n < strong_min_claims:
            return {**a, 'tier': 'moderate', 'reasons': a['reasons'] + [f'fewer than {strong_min_claims} distinct claims']}
    return a


def recommend(index, service_text, location_text, k=MAX_RESULTS, bands=BANDS_KM, strong_min_claims=None, review=True):
    service = resolve_service(service_text)
    if not service:
        return {'error': f'Unknown service "{service_text}". Choose one of: '
                         + ', '.join(s['label'] for s in SERVICES.values())}
    origin = index.gaz.resolve(location_text)
    if 'error' in origin:
        return {'error': origin['error']}
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
    order = lambda s: (s[0], round(s[1], 1), -len(s[3]['evidence']), text(index.rows[s[2]].get('unique_id')))
    counts = {b: {t: sum(1 for s in scored if s[1] <= b and TIERS[s[0]] == t) for t in ('strong', 'moderate', 'weak')}
              for b in bands}

    chosen_band, results, extra, runner_ups = None, [], None, []
    for b in bands:
        in_band = sorted([s for s in scored if s[1] <= b], key=order)
        if not any(s[0] <= 1 for s in in_band):
            continue
        chosen_band = b
        cards = _dedupe([_card(index, s[2], s[3], s[1]) for s in in_band if s[0] <= 1])
        results = cards[:k]
        weak = _dedupe([_card(index, s[2], s[3], s[1]) for s in in_band if s[0] == 2])
        shown = {_name_key(c['name']) for c in results}
        pool = cards[k:] + [w for w in weak if _name_key(w['name']) not in shown]
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
        c['why_ranked'] = (f"#{rank} of {n_in_band} facilities with credible evidence within {chosen_band} km; "
                           f"ordered by evidence strength, then distance.")

    result = {
        'contract_version': CONTRACT_VERSION,
        'service': service, 'service_label': SERVICES[service]['label'], 'service_scope': SERVICES[service]['scope'],
        'origin': origin, 'band_km': chosen_band, 'results': results, 'runner_ups': runner_ups,
        'farther_stronger': extra, 'nearest_beyond': beyond, 'weak_nearby': weak_nearby,
        'considered': {'by_band': counts, 'recommendable_without_location': no_distance},
        'parameters': {'bands_km': list(bands), 'max_results': k, 'strong_min_claims': strong_min_claims},
        'method': ('Strong/Moderate evidence only; nearest distance band (' + '/'.join(map(str, bands)) + ' km) that has '
                   'any; within it, stronger evidence first, then shorter straight-line distance.'),
        'disclaimer': ('Based on public web listings, not verified by the facility. Availability today is unknown: '
                       'call before travelling. Distances are straight-line, not road travel time.'),
    }
    if review:
        from .review import review as run_review
        result['review'] = run_review(index, result)
    return result
