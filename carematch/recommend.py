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

from .decision import assumptions as decision_assumptions
from .decision import cost_info, drive_minutes, normalize_preferences
from .decision import score as preference_score
from .evidence import TIERS, assess, foreign_mentions, record_mixing
from .geo import CITY_ALIASES, Gazetteer, city_key, facility_location
from .services import SERVICES, resolve_service
from .textutil import fragments, haversine_km, normalize, source_urls, text

CONTRACT_VERSION = '1.1'
BANDS_KM = (25, 75, 150, 300)
MAX_RESULTS = 3
MAX_RUNNER_UPS = 3
DEDUP_KM = 2.0
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


def _apply_variant(a, strong_min_claims):
    """Sensitivity variant: require more distinct claims for Strong."""
    if strong_min_claims and a['tier'] == 'strong':
        n = len({normalize(e['text']) for e in a['evidence'] if e['kind'] == 'direct'})
        if n < strong_min_claims:
            return {**a, 'tier': 'moderate', 'reasons': a['reasons'] + [f'fewer than {strong_min_claims} distinct claims']}
    return a


def recommend(index, service_text, location_text, k=MAX_RESULTS, bands=BANDS_KM, strong_min_claims=None, review=True,
              preferences=None):
    """preferences: optional {'urgency': 'default'|'time_critical'|'can_travel', 'cost': 'any'|'low_cost'}.
    Without preferences (or with both defaults) the output is exactly the evidence-then-distance ranking."""
    prefs = normalize_preferences(preferences)
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

    first_ask = SERVICES[service]['ask'][0]
    if not results:
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
        'service': service, 'service_label': SERVICES[service]['label'], 'service_scope': SERVICES[service]['scope'],
        'origin': origin, 'band_km': chosen_band, 'action_advice': advice, 'results': results, 'runner_ups': runner_ups,
        'farther_stronger': extra, 'nearest_beyond': beyond, 'weak_nearby': weak_nearby,
        'considered': {'by_band': counts, 'recommendable_without_location': no_distance},
        'parameters': {'bands_km': list(bands), 'max_results': k, 'strong_min_claims': strong_min_claims},
        'preferences': prefs,
        **({'preference_model': decision_assumptions(prefs), 'default_order_ids': default_ids,
            'cost_unknown_options': cost_unknown, 'tradeoff_note': tradeoff} if prefs['applied'] else {}),
        'method': ('Strong/Moderate evidence only; nearest distance band (' + '/'.join(map(str, bands)) + ' km) that has '
                   'any; within it, stronger evidence first, then shorter straight-line distance.'),
        'disclaimer': ('Based on public web listings, not verified by the facility. Availability today is unknown: '
                       'call before travelling. Distances are straight-line, not road travel time.'),
    }
    if review:
        from .review import review as run_review
        result['review'] = run_review(index, result)
    return result
