"""Service + location -> up to 3 facilities, each with quoted evidence, distance and stated uncertainty.

Ranking rule (docs/design.md):
  1. Only facilities with Strong or Moderate evidence are recommended.
  2. Distance bands from the user: 25, 75, 150, 300 km. Use the nearest band that has any recommendable facility.
  3. Inside the band: evidence tier first, then distance, then number of distinct claims.
  4. If the band has only Moderate options and the next band has a Strong one, add it as "farther, stronger evidence".
  5. Nothing within 300 km -> no recommendation; show the nearest option beyond and nearby weak mentions, labelled.
"""
import csv
import re
import sys

from .evidence import TIERS, assess
from .geo import Gazetteer, facility_location
from .services import SERVICES, resolve_service
from .textutil import fragments, haversine_km, normalize, source_urls, text

BANDS_KM = (25, 75, 150, 300)
MAX_RESULTS = 3
DEDUP_KM = 2.0

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
        self._assessed = {}

    @classmethod
    def from_csv(cls, facilities_path='data/facilities.csv', pincodes_path='data/pincodes.csv'):
        return cls(load_csv(facilities_path), load_csv(pincodes_path))

    def assessments(self, service):
        if service not in self._assessed:
            self._assessed[service] = [assess(r, service) for r in self.rows]
        return self._assessed[service]


def _card(index, i, a, origin, dist):
    row, loc = index.rows[i], index.locations[i]
    phones = fragments(row.get('phone_numbers'))
    official = text(row.get('officialPhone'))
    website = text(row.get('officialWebsite'))
    urls = source_urls(row.get('source_urls'))
    urls = sorted(urls, key=lambda u: (any(d in u for d in AGGREGATORS), len(u)))
    quotes = [e for e in a['evidence'] if e['kind'] in ('direct', 'listed')][:3]
    if not quotes:
        quotes = a['evidence'][:2]
    flags = sorted(set(a['flags']) | set(f for f in loc['flags'] if f in FLAG_TEXT))
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
        'distance_km': round(dist, 1) if dist is not None else None,
        'distance_basis': loc['basis'], 'location_confidence': loc['confidence'],
        'tier': a['tier'], 'tier_reasons': a['reasons'],
        'evidence': [{'evidence_id': e['evidence_id'], 'field': e['field'], 'quote': e['text'], 'kind': e['kind']} for e in quotes],
        'all_evidence_count': len(a['evidence']),
        'n_claims': len({normalize(e['text']) for e in a['evidence'] if e['kind'] in ('direct', 'listed')}),
        'flags': flags, 'uncertainties': [FLAG_TEXT[f] for f in flags if f in FLAG_TEXT],
        'source_urls': urls[:3],
        'ask_when_calling': SERVICES[a['service']]['ask'],
    }


def _dedupe(cards):
    """Merge listings with the same normalized name within DEDUP_KM (or same name and no distance)."""
    kept = []
    for c in cards:
        dup = next((k for k in kept if _name_key(k['name']) == _name_key(c['name'])
                    and (k['distance_km'] is None or c['distance_km'] is None
                         or abs(k['distance_km'] - c['distance_km']) <= DEDUP_KM)), None)
        if dup:
            dup.setdefault('merged_ids', []).append(c['facility_id'])
            if 'possible_duplicate_listing' not in dup['flags']:
                dup['flags'].append('possible_duplicate_listing')
                dup['uncertainties'].append(FLAG_TEXT['possible_duplicate_listing'])
        else:
            kept.append(c)
    return kept


def recommend(index, service_text, location_text, k=MAX_RESULTS):
    service = resolve_service(service_text)
    if not service:
        return {'error': f'Unknown service "{service_text}". Choose one of: '
                         + ', '.join(s['label'] for s in SERVICES.values())}
    origin = index.gaz.resolve(location_text)
    if 'error' in origin:
        return {'error': origin['error']}
    o = (origin['lat'], origin['lon'])

    scored = []          # (tier_rank, distance, -claims, i, assessment)
    no_distance = 0
    for i, a in enumerate(index.assessments(service)):
        if a['tier'] == 'none':
            continue
        dist = _distance(o, index.locations[i])
        if dist is None:
            no_distance += a['tier'] in ('strong', 'moderate')
            continue
        tier = a['tier']
        if index.locations[i]['confidence'] == 'low' and tier == 'strong':
            a = {**a, 'tier': 'moderate', 'reasons': a['reasons'] + ['location data conflicts, so treated as moderate'],
                 'flags': a['flags'] + ['location_conflict']}
            tier = 'moderate'
        scored.append((TIERS.index(tier), dist, i, a))

    eligible = [s for s in scored if s[0] <= 1]
    counts = {}
    for b in BANDS_KM:
        counts[b] = {t: sum(1 for s in scored if s[1] <= b and TIERS[s[0]] == t) for t in ('strong', 'moderate', 'weak')}

    chosen_band, results, extra = None, [], None
    for b in BANDS_KM:
        in_band = [s for s in eligible if s[1] <= b]
        if not in_band:
            continue
        chosen_band = b
        in_band.sort(key=lambda s: (s[0], round(s[1], 1), -len(s[3]['evidence'])))
        cards = _dedupe([_card(index, s[2], s[3], o, s[1]) for s in in_band])
        results = cards[:k]
        if all(c['tier'] != 'strong' for c in results):
            nxt = BANDS_KM[BANDS_KM.index(b) + 1] if b != BANDS_KM[-1] else None
            stronger = sorted([s for s in eligible if s[0] == 0 and (nxt is None or s[1] <= nxt) and s[1] > b],
                              key=lambda s: s[1])
            if stronger:
                extra = _card(index, stronger[0][2], stronger[0][3], o, stronger[0][1])
                extra['note'] = 'Farther away, but stronger evidence than the options above.'
        break

    beyond, weak_nearby = None, []
    if not results:
        far = sorted(eligible, key=lambda s: (s[1], s[0]))
        if far:
            beyond = _card(index, far[0][2], far[0][3], o, far[0][1])
            beyond['note'] = f'Nearest facility with credible evidence, beyond {BANDS_KM[-1]} km.'
        weak = sorted([s for s in scored if s[0] == 2 and s[1] <= BANDS_KM[1]], key=lambda s: s[1])[:3]
        weak_nearby = [_card(index, s[2], s[3], o, s[1]) for s in weak]

    for rank, c in enumerate(results, 1):
        c['rank'] = rank
        c['why_ranked'] = (f"#{rank} of {len([s for s in eligible if s[1] <= chosen_band])} facilities with credible "
                           f"evidence within {chosen_band} km; ordered by evidence strength, then distance.")

    return {
        'service': service, 'service_label': SERVICES[service]['label'],
        'origin': origin, 'band_km': chosen_band, 'results': results, 'farther_stronger': extra,
        'nearest_beyond': beyond, 'weak_nearby': weak_nearby,
        'considered': {'by_band': counts, 'recommendable_without_location': no_distance},
        'method': ('Strong/Moderate evidence only; nearest distance band (25/75/150/300 km) that has any; '
                   'within it, stronger evidence first, then shorter straight-line distance.'),
        'disclaimer': ('Based on public web listings, not verified by the facility. Availability today is unknown: '
                       'call before travelling. Distances are straight-line, not road travel time.'),
    }
