"""Locations: turn user input into a point, and judge how far to trust each facility's position.

User input can be "lat, lon", a 6-digit PIN code, or a city / district name (optionally "name, state").
Facility positions come from the record's latitude/longitude, cross-checked against the India Post PIN
directory and against the other facilities listed in the same city.
"""
import re
import statistics

from .textutil import haversine_km, normalize, text, valid_coords

STATES = ['Andaman And Nicobar Islands', 'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chandigarh',
          'Chhattisgarh', 'Delhi', 'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jammu And Kashmir', 'Jharkhand',
          'Karnataka', 'Kerala', 'Ladakh', 'Lakshadweep', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya',
          'Mizoram', 'Nagaland', 'Odisha', 'Puducherry', 'Punjab', 'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana',
          'The Dadra And Nagar Haveli And Daman And Diu', 'Tripura', 'Uttar Pradesh', 'Uttarakhand', 'West Bengal']
_STATE_KEYS = {normalize(s): s for s in STATES}
_STATE_ALIASES = {
    'nct of delhi': 'Delhi', 'new delhi': 'Delhi', 'delhi ncr': 'Delhi', 'tamilnadu': 'Tamil Nadu', 'orissa': 'Odisha',
    'up': 'Uttar Pradesh', 'u.p.': 'Uttar Pradesh', 'mp': 'Madhya Pradesh', 'punjab region': 'Punjab',
    'j&k': 'Jammu And Kashmir', 'jammu & kashmir': 'Jammu And Kashmir', 'pondicherry': 'Puducherry',
    'uttaranchal': 'Uttarakhand', 'chattisgarh': 'Chhattisgarh', 'dadra and nagar haveli': 'The Dadra And Nagar Haveli And Daman And Diu',
    'daman and diu': 'The Dadra And Nagar Haveli And Daman And Diu', 'telengana': 'Telangana', 'west bangal': 'West Bengal',
}

# Facility city spellings that refer to the same place (verified counts in docs/data_profile.md).
CITY_ALIASES = {
    'bangalore': 'bengaluru', 'bengaluru': 'bengaluru', 'gurgaon': 'gurugram', 'gurugram': 'gurugram',
    'new delhi': 'delhi', 'delhi': 'delhi', 'trivandrum': 'thiruvananthapuram', 'cochin': 'kochi',
    'vizag': 'visakhapatnam', 'bombay': 'mumbai', 'madras': 'chennai', 'calcutta': 'kolkata',
    'poona': 'pune', 'mysore': 'mysuru', 'baroda': 'vadodara', 'benares': 'varanasi', 'banaras': 'varanasi',
    'allahabad': 'prayagraj', 'calicut': 'kozhikode', 'mangalore': 'mangaluru', 'belgaum': 'belagavi',
}

PIN_RE = re.compile(r'\b([1-9]\d{5})\b')
COORD_RE = re.compile(r'^\s*(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{2,3}(?:\.\d+)?)\s*$')

# Trust thresholds (km)
PIN_SPREAD_OK = 60        # a PIN whose post offices span more than this is a poor reference point
COORD_PIN_CONFLICT = 50   # facility coordinates this far from their PIN centroid -> location conflict
CITY_OUTLIER = 100        # this far from the median of other facilities in the same city -> outlier


def canonical_state(value):
    key = normalize(value).replace('state of ', '')
    return _STATE_KEYS.get(key) or _STATE_ALIASES.get(key)


def city_key(value):
    key = normalize(value)
    return CITY_ALIASES.get(key, key)


def clean_pin(value):
    m = PIN_RE.search(text(value).replace(' ', ''))
    return m.group(1) if m else None


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


class Gazetteer:
    """PIN, district and city lookups built from the PIN directory and the facilities table."""

    def __init__(self, pincode_rows, facility_rows):
        self.pins = {}
        districts = {}
        for r in pincode_rows:
            pin = clean_pin(r.get('pincode'))
            if not pin:
                continue
            centre = valid_coords(r.get('lat'), r.get('lon'))
            box = [_num(r.get(k)) for k in ('lat_min', 'lat_max', 'lon_min', 'lon_max')]
            spread = None
            if centre and None not in box:
                spread = haversine_km((box[0], box[2]), (box[1], box[3]))
            state = canonical_state(r.get('statename'))
            entry = {'pin': pin, 'district': text(r.get('district')).title(), 'state': state,
                     'centre': centre, 'spread_km': spread, 'n_offices': int(_num(r.get('n_offices')) or 0)}
            self.pins.setdefault(pin, []).append(entry)
        self._drop_misgeocoded_pins()
        for entries in self.pins.values():
            for entry in entries:
                if entry['centre'] and entry['spread_km'] is not None and entry['spread_km'] <= PIN_SPREAD_OK and entry['district']:
                    districts.setdefault((normalize(entry['district']), entry['state']), []).append(entry['centre'])
        self.districts = {}
        for (dname, state), pts in districts.items():
            self.districts.setdefault(dname, []).append(self._cluster(pts, state, f'{dname.title()} district'))

        cities = {}
        for r in facility_rows:
            c = valid_coords(r.get('latitude'), r.get('longitude'))
            key = city_key(r.get('address_city'))
            if c and key and key not in ('null', 'none'):
                state = canonical_state(r.get('address_stateOrRegion'))
                cities.setdefault((key, state), []).append(c)
        self.cities = {}
        for (key, state), pts in cities.items():
            if len(pts) >= 2:
                self.cities.setdefault(key, []).append(self._cluster(pts, state, key.title()))

    def _drop_misgeocoded_pins(self):
        """Some post offices were geocoded to a same-named place in another state (e.g. Aurangabad, Bihar
        PINs 824xxx placed in Aurangabad, Maharashtra). PINs sharing leading digits are in the same postal
        region, so a centre far from its region's median is discarded."""
        self.dropped_pins = 0
        for digits, limit in ((2, 400.0), (3, 150.0)):
            groups = {}
            for pin, entries in self.pins.items():
                for e in entries:
                    if e['centre']:
                        groups.setdefault(pin[:digits], []).append(e['centre'])
            medians = {k: (statistics.median(p[0] for p in v), statistics.median(p[1] for p in v))
                       for k, v in groups.items() if len(v) >= 5}
            for pin, entries in self.pins.items():
                ref = medians.get(pin[:digits])
                for e in entries:
                    if e['centre'] and ref and haversine_km(e['centre'], ref) > limit:
                        e['centre'], e['spread_km'] = None, None
                        self.dropped_pins += 1

    @staticmethod
    def _cluster(pts, state, label):
        centre = (statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts))
        radius = statistics.median(haversine_km(centre, p) for p in pts) if len(pts) > 1 else 5.0
        return {'label': label, 'state': state, 'centre': centre, 'radius_km': radius, 'n': len(pts)}

    # ---- PIN ---------------------------------------------------------------
    def pin_info(self, pin):
        """Best entry for a PIN plus whether it spans several districts/states."""
        entries = self.pins.get(pin)
        if not entries:
            return None
        good = [e for e in entries if e['centre']]
        best = max(good or entries, key=lambda e: e['n_offices'])
        return {**best, 'districts': sorted({e['district'] for e in entries}),
                'states': sorted({e['state'] for e in entries if e['state']}),
                'reliable': bool(best['centre']) and best['spread_km'] is not None and best['spread_km'] <= PIN_SPREAD_OK}

    # ---- user input --------------------------------------------------------
    def resolve(self, query):
        """Return a location dict, or a dict with 'error'."""
        raw = text(query)
        if not raw:
            return {'error': 'Please enter a place: city, district, 6-digit PIN code, or "lat, lon".'}
        m = COORD_RE.match(raw)
        if m:
            c = valid_coords(m.group(1), m.group(2))
            if not c:
                return {'error': f'"{raw}" is not a coordinate inside India.'}
            return self._loc(raw, 'coordinates', f'{c[0]:.4f}, {c[1]:.4f}', c, 0.1)
        pin = clean_pin(raw) if re.fullmatch(r'\s*\d[\d ]{4,6}\d?\s*', raw) else None
        if pin:
            return self._resolve_pin(raw, pin)
        name, _, state_hint = raw.partition(',')
        state = canonical_state(state_hint) if state_hint.strip() else None
        lookups = (('city', self.cities, city_key(name)), ('district', self.districts, normalize(name)))
        # With a state hint, first look for an exact state match in either index, then relax.
        passes = (True, False) if state else (False,)
        for strict in passes:
            for kind, index, key in lookups:
                found = index.get(key)
                if not found and kind == 'district' and len(key) >= 3:
                    # word-level fallback: "leh" -> "leh ladakh", "kanpur" -> "kanpur nagar"
                    found = [o for k, opts in index.items() if key in k.split() for o in opts]
                options = [o for o in found or [] if o['state']] or (found or [])
                if strict:
                    options = [o for o in options if o['state'] == state]
                if not options:
                    continue
                options = sorted(options, key=lambda o: -o['n'])
                best = options[0]
                label = best['label'] + (f", {best['state']}" if best['state'] else '')
                loc = self._loc(raw, kind, label, best['centre'], max(3.0, best['radius_km']), state=best['state'])
                if not strict and state and best['state'] != state:
                    loc['notes'].append(f'No "{name.strip()}" found in {state}; showing {label}.')
                others = {o['state'] for o in options[1:] if o['state']}
                if kind == 'city':   # a district elsewhere can share the city's name (Aurangabad, Bihar)
                    others |= {o['state'] for o in self.districts.get(normalize(name)) or [] if o['state']}
                others = sorted(others - {best['state']})
                if others and not state:
                    loc['alternatives'] = [f'{name.strip()}, {s}' for s in others]
                    loc['notes'].append(f'"{name.strip()}" also exists in {", ".join(others)}; showing {best["state"]}. '
                                        f'Type "{name.strip()}, {others[0]}" to switch.')
                if kind == 'city':
                    loc['notes'].append('Distances are measured from the centre of the listed facilities in this city.')
                return loc
        return {'error': f'Could not find "{raw}". Try a 6-digit PIN code, a district name, or "lat, lon".'}

    def _resolve_pin(self, raw, pin):
        info = self.pin_info(pin)
        if info and info['reliable']:
            loc = self._loc(raw, 'pin', f"PIN {pin} ({info['district']}, {info['state']})", info['centre'],
                            max(2.0, info['spread_km'] / 2), state=info['state'], district=info['district'])
            if len(info['districts']) > 1:
                loc['notes'].append(f"PIN {pin} covers several districts: {', '.join(info['districts'])}.")
            return loc
        # Fall back to nearby PINs sharing the first 4 digits (same postal sub-region).
        near = [e['centre'] for p, es in self.pins.items() if p.startswith(pin[:4]) for e in es
                if e['centre'] and e['spread_km'] is not None and e['spread_km'] <= PIN_SPREAD_OK]
        if near:
            c = (statistics.median(p[0] for p in near), statistics.median(p[1] for p in near))
            loc = self._loc(raw, 'pin_area', f'PIN area {pin[:4]}xx', c, 25.0)
            loc['notes'].append(f'PIN {pin} has no reliable location in the India Post directory; '
                                f'using the centre of nearby PINs {pin[:4]}xx (approximate).')
            return loc
        return {'error': f'PIN {pin} was not found in the India Post directory.'}

    @staticmethod
    def _loc(query, kind, label, centre, precision, state=None, district=None):
        return {'query': query, 'kind': kind, 'label': label, 'lat': round(centre[0], 5), 'lon': round(centre[1], 5),
                'precision_km': round(precision, 1), 'state': state, 'district': district, 'notes': [], 'alternatives': []}


def facility_location(row, gaz):
    """Position used for distance + a confidence level and plain flags for one facility record.

    Three independent signals are compared: the record's coordinates, the centre of its PIN code,
    and the centre of other facilities listed in the same city. When two agree and one does not,
    the odd one out is treated as the error (e.g. coordinates 500 km away while PIN and city agree).
    """
    coord = valid_coords(row.get('latitude'), row.get('longitude'))
    pin = clean_pin(row.get('address_zipOrPostcode'))
    info = gaz.pin_info(pin) if pin else None
    pin_pt = info['centre'] if info and info['reliable'] else None
    state_raw = text(row.get('address_stateOrRegion'))
    state = canonical_state(state_raw)
    city = [c for c in gaz.cities.get(city_key(row.get('address_city'))) or []
            if c['n'] >= 5 and (not state or c['state'] == state)]
    city_best = max(city, key=lambda c: c['n']) if city else None
    city_pt = city_best['centre'] if city_best else None
    # "Same city" radius scales with how spread out the city's facilities are (25-60 km).
    city_km = min(CITY_OUTLIER, max(25.0, 4 * city_best['radius_km'])) if city_best else CITY_OUTLIER
    flags = []

    if not pin:
        flags.append('pin_missing_or_malformed')
    elif not info:
        flags.append('pin_not_in_directory')
    if state_raw and normalize(state_raw) not in ('null', 'none') and not state:
        flags.append('state_field_not_a_state')
    if state and info and info['states'] and state not in info['states']:
        flags.append('state_pin_mismatch')

    near = lambda a, b, km: a is not None and b is not None and haversine_km(a, b) <= km
    position, basis, confidence = coord, 'facility coordinates', 'high'
    alternatives = []      # other plausible positions; distance uses the farthest (conservative)
    if coord:
        coord_pin = None if pin_pt is None else near(coord, pin_pt, COORD_PIN_CONFLICT)
        coord_city = None if city_pt is None else near(coord, city_pt, city_km)
        pin_city = None if pin_pt is None or city_pt is None else near(pin_pt, city_pt, city_km)
        if coord_pin is False and coord_city is False and pin_city:
            position, basis, confidence = pin_pt, 'PIN code centre (record coordinates contradict PIN and city)', 'approximate'
            flags.append('coords_wrong_used_pin')
        elif coord_pin is False and coord_city:
            flags.append('pin_inconsistent')          # coordinates agree with the city; the PIN looks wrong
            confidence = 'medium'
        elif coord_pin is False or coord_city is False:
            flags.append('location_conflict')         # cannot tell which signal is right
            confidence = 'low'
            alternatives = [p for p in (pin_pt, city_pt) if p is not None and not near(p, coord, 10)]
    elif pin_pt:
        position, basis, confidence = pin_pt, 'PIN code centre (approximate)', 'approximate'
        flags.append('position_from_pin')
    elif city_pt:
        position, basis, confidence = city_pt, 'city centre (approximate)', 'low'
        flags.append('position_from_city')
    else:
        position, basis, confidence = None, None, 'low'
        flags.append('no_location')
    if confidence == 'high' and flags:
        confidence = 'medium'
    return {'position': position, 'alternatives': alternatives, 'basis': basis, 'confidence': confidence, 'flags': flags,
            'pin': pin, 'state': state or (info['states'][0] if info and len(info['states']) == 1 else None),
            'district': info['district'] if info else None}
