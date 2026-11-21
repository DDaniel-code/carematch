"""Access gaps for planners: how far each district's people are from a facility with credible evidence.

Unit of analysis: India Post PIN areas with a reliable centre (spread <= 60 km), weighted by their number of post
offices as a rough stand-in for settlements. For each area and service we take the straight-line distance to the
nearest facility whose evidence is Strong or Moderate (same rules as recommend()), then summarise by district and
put NFHS-5 district indicators next to it.

NFHS figures describe need in a district. They never enter recommend(): a district's need says nothing about the
quality of any one facility.
"""
import csv
import difflib
import math
import re
import statistics
import sys

from .geo import PIN_SPREAD_OK, canonical_state
from .textutil import haversine_km, normalize, text

NEAR_KM = 50                 # an area farther than this from the nearest credible facility counts as "far"
FAR_SHARE = 0.5              # a district is an access gap when at least half its post offices are far
FEW_HOSPITALS = 3            # fewer hospital listings (any service) than this near a district: likely a data gap
LOW_CSECTION_PCT = 5.0       # UN EmOC monitoring guidelines: a population caesarean rate below 5% signals unmet need
KM_PER_DEG = 111.2
MIN_KM_PER_DEG_LON = 88.0    # 111.2 * cos(37.5 deg), India's northern edge: a safe lower bound for longitude

NFHS_FIELDS = {
    'csection_pct': 'births_delivered_by_csection_5y_pct',
    'institutional_birth_pct': 'institutional_birth_5y_pct',
    'high_sugar_women_pct': 'w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct',
    'high_sugar_men_pct': 'm15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct',
    'insured_pct': 'hh_member_covered_health_insurance_pct',
}


class PointIndex:
    """Nearest-neighbour and radius counts on a lat/lon grid (standard library only)."""

    def __init__(self, points, cell_deg=0.5):
        self.cell = cell_deg
        self.grid = {}
        for p in points:          # p = (lat, lon, key)
            self.grid.setdefault(self._key(p[0], p[1]), []).append(p)

    def _key(self, lat, lon):
        return int(math.floor(lat / self.cell)), int(math.floor(lon / self.cell))

    def _ring(self, centre, r):
        ci, cj = centre
        for i in range(ci - r, ci + r + 1):
            for j in range(cj - r, cj + r + 1):
                if max(abs(i - ci), abs(j - cj)) == r:
                    yield from self.grid.get((i, j), ())

    def nearest(self, lat, lon, max_km=3500):
        if not self.grid:
            return None, None
        centre, best, best_key = self._key(lat, lon), None, None
        step_km = self.cell * MIN_KM_PER_DEG_LON
        for r in range(int(max_km / step_km) + 2):
            if best is not None and (r - 1) * step_km > best:
                break
            for p in self._ring(centre, r):
                d = haversine_km((lat, lon), (p[0], p[1]))
                if best is None or d < best:
                    best, best_key = d, p[2]
        return best, best_key

    def keys_within(self, lat, lon, km):
        centre = self._key(lat, lon)
        out = set()
        for r in range(int(km / (self.cell * MIN_KM_PER_DEG_LON)) + 2):
            for p in self._ring(centre, r):
                if haversine_km((lat, lon), (p[0], p[1])) <= km:
                    out.add(p[2])
        return out


# ---- inputs from the engine ----------------------------------------------------------------------------------------

def credible_points(index, service):
    """(lat, lon, facility group) for every positioned facility with Strong or Moderate evidence for the service."""
    pts = []
    for i, a in enumerate(index.assessments(service)):
        pos = index.locations[i]['position']
        if a['tier'] in ('strong', 'moderate') and pos:
            pts.append((pos[0], pos[1], index.dup_group[i]))
    return pts


def hospital_points(index):
    """Every positioned hospital listing, whatever it claims: how well the dataset covers an area at all."""
    return [(index.locations[i]['position'][0], index.locations[i]['position'][1], index.dup_group[i])
            for i, r in enumerate(index.rows)
            if index.locations[i]['position'] and normalize(r.get('facilityTypeId')) == 'hospital']


def districts(index):
    """{(district, state): [(lat, lon, offices), ...]} from PIN areas with a reliable centre."""
    out = {}
    for entries in index.gaz.pins.values():
        for e in entries:
            if e['centre'] and e['spread_km'] is not None and e['spread_km'] <= PIN_SPREAD_OK and e['district'] and e['state']:
                out.setdefault((e['district'], e['state']), []).append((e['centre'][0], e['centre'][1], max(1, e['n_offices'])))
    return out


def _weighted_median(pairs):
    pairs = sorted(pairs)
    total, run = sum(w for _, w in pairs), 0
    for v, w in pairs:
        run += w
        if run >= total / 2:
            return v
    return None


# ---- NFHS -------------------------------------------------------------------------------------------------------------

def nfhs_number(value):
    """NFHS cell -> (value, small_sample). '*' = suppressed; '(12.3)' = based on 25-49 cases."""
    s = text(value).strip()
    if not s or s == '*':
        return None, False
    small = s.startswith('(')
    try:
        return float(s.strip('()').strip()), small
    except ValueError:
        return None, False


def _dkey(name):
    return re.sub(r'[^a-z0-9]+', ' ', normalize(name).replace('&', ' and ')).strip()


def _skey(state):
    return canonical_state(state) or _dkey(state)


def match_nfhs(district_keys, nfhs_rows):
    """Map (district, state) -> NFHS row. Exact name within state, then a close spelling within state."""
    by_state = {}
    for row in nfhs_rows:
        by_state.setdefault(_skey(row.get('state_ut')), {})[_dkey(row.get('district_name'))] = row
    mapping, how = {}, {'exact': 0, 'close_spelling': 0, 'unmatched': 0}
    for district, state in district_keys:
        options = by_state.get(_skey(state)) or {}
        k = _dkey(district)
        if k in options:
            mapping[(district, state)] = options[k]
            how['exact'] += 1
            continue
        close = difflib.get_close_matches(k, list(options), n=1, cutoff=0.85)
        if close:
            mapping[(district, state)] = options[close[0]]
            how['close_spelling'] += 1
        else:
            how['unmatched'] += 1
    return mapping, how


# ---- analysis ---------------------------------------------------------------------------------------------------------

def district_table(index, services, nfhs_rows=None):
    """One row per district: per-service access figures, dataset coverage, and NFHS need indicators."""
    areas = districts(index)
    hospitals = PointIndex(hospital_points(index))
    credible = {s: PointIndex(credible_points(index, s)) for s in services}
    nfhs, match_stats = match_nfhs(list(areas), nfhs_rows or [])
    area_distances = {s: [] for s in services}     # every PIN area: (km to nearest credible facility, post offices)

    table = []
    for (district, state), pts in sorted(areas.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        centre = (statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts))
        row = {'district': district, 'state': state, 'pin_areas': len(pts), 'post_offices': sum(p[2] for p in pts),
               'lat': round(centre[0], 4), 'lon': round(centre[1], 4),
               'hospitals_listed_within_50km': len(hospitals.keys_within(centre[0], centre[1], NEAR_KM))}
        offices = row['post_offices']
        for s in services:
            near = [(credible[s].nearest(lat, lon)[0], w) for lat, lon, w in pts]
            area_distances[s].extend(near)
            known = [(d, w) for d, w in near if d is not None]
            row[f'{s}_median_km'] = round(_weighted_median(known), 1) if known else None
            row[f'{s}_share_far'] = round(sum(w for d, w in near if d is None or d > NEAR_KM) / offices, 3)
            row[f'{s}_credible_within_50km'] = len(credible[s].keys_within(centre[0], centre[1], NEAR_KM))
        source = nfhs.get((district, state))
        row['nfhs_district'] = text(source.get('district_name')).strip() if source else None
        for name, col in NFHS_FIELDS.items():
            value, small = nfhs_number(source.get(col)) if source else (None, False)
            row[name] = value
            row[f'{name}_small_sample'] = small
        table.append(row)
    national = {s: coverage(area_distances[s], table, s) for s in services}
    return table, match_stats, national


def coverage(area_distances, table, service, thresholds=(25, 50, 100)):
    """Share of all post offices within each straight-line distance of a credible facility, plus gap-district count."""
    total = sum(w for _, w in area_distances)
    out = {f'within_{km}km': round(sum(w for d, w in area_distances if d is not None and d <= km) / total, 3)
           for km in thresholds} if total else {}
    out['districts_with_access_gap'] = sum(1 for r in table if r[f'{service}_share_far'] >= FAR_SHARE)
    out['districts'] = len(table)
    return out


def gap_kind(row):
    """Why there is no credible facility nearby: the dataset barely covers the area, or it lists hospitals that do not
    document this service."""
    return 'data gap (few listings at all)' if row['hospitals_listed_within_50km'] < FEW_HOSPITALS else \
        'service gap (hospitals listed, none documents this service)'


def maternal_priorities(table):
    """Districts where most people are far from credible C-section care AND NFHS shows the operation is rarely done."""
    rows = [r for r in table if r['c_section_share_far'] >= FAR_SHARE
            and r['csection_pct'] is not None and r['csection_pct'] < LOW_CSECTION_PCT]
    return sorted(rows, key=lambda r: (r['csection_pct'], -(r['c_section_median_km'] or 0)))


def dialysis_priorities(table, top_share=0.25):
    """Districts far from credible dialysis AND in the top quarter for raised blood sugar (diabetes drives kidney failure)."""
    def sugar(r):
        vals = [v for v in (r['high_sugar_women_pct'], r['high_sugar_men_pct']) if v is not None]
        return sum(vals) / len(vals) if vals else None
    scored = [(sugar(r), r) for r in table if sugar(r) is not None]
    if not scored:
        return []
    cut = sorted(v for v, _ in scored)[int(len(scored) * (1 - top_share))]
    rows = [r for v, r in scored if v >= cut and r['dialysis_share_far'] >= FAR_SHARE]
    for r in rows:
        r['_sugar'] = round(sugar(r), 1)
    return sorted(rows, key=lambda r: -(r['dialysis_median_km'] or 0))


def write_csv(rows, path, fields=None):
    csv.field_size_limit(sys.maxsize)
    fields = fields or [k for k in rows[0] if not k.startswith('_')]
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
