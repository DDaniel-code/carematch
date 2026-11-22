"""Read the call team's published CSVs and reconcile the map with its plan."""
import csv
import json
import math
import re


def _read(directory, suffix, required):
    path = directory / f'c_section_{suffix}.csv'
    with path.open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        missing = set(required.split()) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f'{path.name} lacks {", ".join(sorted(missing))}')
        return list(reader)


def _flag(value):
    value = value.strip().lower()
    if value in ('1', 'true', 'yes'):
        return True
    if value in ('0', 'false', 'no'):
        return False
    raise ValueError(f'Unrecognised flag {value!r}')


def load_map(directory, first_failed=False):
    pins = _read(directory, 'pin_status', 'pin lat lon district state reliable covered_now nearest_credible_km nearest_credible_tier nearest_facility_id newly_covered_at_rank')
    plan_fields = 'rank facility_id name new_pin_ids marginal_gain cumulative_gain'
    calls = _read(directory, 'call_plan', plan_fields)
    excluded_id = None
    alternate_ranks = {}
    if first_failed and calls:
        excluded_id = min(calls, key=lambda c: int(c['rank']))['facility_id']
        calls = _read(directory, 'call_plan_if_first_fails', plan_fields)
        for c in calls:
            for pin in c['new_pin_ids'].split(';'):
                alternate_ranks[pin.strip()] = int(c['rank'])
    leads = _read(directory, 'call_candidates', 'facility_id phone lead_fields lead_quotes call_questions')
    by_id = {row['facility_id']: row for row in leads}
    by_rank = {}
    seen = set()
    points = []
    excluded = 0
    for row in pins:
        pin = row['pin']
        if not re.fullmatch('[0-9]{6}', pin) or pin in seen:
            raise ValueError(f'Invalid or duplicate PIN {pin!r}')
        seen.add(pin)
        rank = int(row['newly_covered_at_rank'] or 0)
        if first_failed:
            rank = alternate_ranks.get(pin, 0)
        if not _flag(row['reliable']):
            if rank or (row['covered_now'] and _flag(row['covered_now'])):
                raise ValueError(f'Unreliable PIN included in coverage: {pin}')
            excluded += 1
            continue
        lat, lon = float(row['lat']), float(row['lon'])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f'Invalid map location for {pin}')
        covered = _flag(row['covered_now'])
        if rank < 0 or (covered and rank):
            raise ValueError(f'Conflicting coverage for {pin}')
        if rank:
            by_rank.setdefault(rank, set()).add(pin)
        km = float(row['nearest_credible_km']) if row['nearest_credible_km'] else None
        if km is not None and (not math.isfinite(km) or km < 0):
            raise ValueError(f'Invalid distance for {pin}')
        points.append(dict(row, lat=lat, lon=lon, covered_now=covered, rank=rank, nearest_credible_km=km))

    cumulative = 0
    selected = set()
    calls.sort(key=lambda c: int(c['rank']))
    for rank, call in enumerate(calls, 1):
        fid = call['facility_id']
        ids = [p.strip() for p in call['new_pin_ids'].split(';') if p.strip()]
        cumulative += len(ids)
        if (int(call['rank']) != rank or fid == excluded_id or fid in selected or fid not in by_id
                or len(set(ids)) != len(ids) or set(ids) != by_rank.pop(rank, set())
                or len(ids) != int(call['marginal_gain']) or cumulative != int(call['cumulative_gain'])):
            raise ValueError(f'PIN map and verification plan disagree at call {rank}')
        selected.add(fid)
        call['candidate'] = by_id[fid]
    if by_rank or not points:
        raise ValueError('PIN map contains unmatched ranks or no reliable centres')
    with (directory / 'c_section_call_plan_summary.json').open(encoding='utf-8') as source:
        summary = json.load(source)
    if (summary['service'] != 'c_section' or summary['radius_km'] != 50
            or summary['pins_total'] != len(seen) or summary['pins_reliable_denominator'] != len(points)
            or summary['pins_covered_now'] != sum(p['covered_now'] for p in points)):
        raise ValueError('Snapshot metadata and PIN coverage disagree')
    return points, calls, excluded
