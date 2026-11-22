"""Build PIN-to-branch distances for the C-section transport scenario map."""
import csv
from pathlib import Path

import numpy as np

from carematch.calls import pin_universe, positions
from carematch.recommend import CareIndex


def distances(lat, lon, point):
    a, b = np.radians(point)
    h = np.sin((lat-a)/2)**2 + np.cos(a)*np.cos(lat)*np.sin((lon-b)/2)**2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def build(index):
    pins, excluded = pin_universe(index)
    keys = list(pins)
    lat, lon = np.radians([pins[p]['centre'] for p in keys]).T
    tiers = ('strong', 'moderate')
    best = {t: np.full(len(keys), np.inf) for t in tiers}
    choice = {t: np.full(len(keys), -1) for t in tiers}
    refs = {}
    for i, assessment in enumerate(index.assessments('c_section')):
        pts = positions(index, i)
        if not pts or assessment['tier'] not in ('strong', 'moderate') or index.mixing[i] or assessment.get('merge_reasons'):
            continue
        ev = next((e for e in assessment['evidence'] if e['kind'] in ('direct', 'listed')), None)
        if not ev:
            continue
        d = np.maximum.reduce([distances(lat, lon, pos) for pos in pts])
        tier = assessment['tier']
        closer = d < best[tier]
        best[tier][closer], choice[tier][closer] = d[closer], i
        refs[i] = (assessment['tier'], ev['field'], ev['text'])
    if any((choice[t] < 0).any() for t in tiers):
        raise ValueError('Missing tier coverage for one or more PINs')
    rows, facilities = [], {}
    for n, p in enumerate(keys):
        info = pins[p]
        tier_data = []
        for t in tiers:
            i = choice[t][n]
            facility = index.rows[i]
            fid = facility['unique_id']
            tier_data.extend((round(best[t][n], 4), fid))
            facilities[fid] = (fid, facility['name'], *refs[i])
        rows.append((p, *info['centre'], info['state'], info['district'], *tier_data))
    return rows, list(facilities.values()), len(excluded)


if __name__ == '__main__':
    rows, refs, excluded = build(CareIndex.from_csv())
    for name, header, contents in [
        ('pins', 'pin lat lon state district strong_km strong_id moderate_km moderate_id', rows),
        ('facilities', 'facility_id name tier field quote', refs),
    ]:
        with Path(f'analysis/travel_{name}.csv').open('w', newline='', encoding='utf-8') as out:
            writer = csv.writer(out)
            writer.writerow(header.split())
            writer.writerows(contents)
    print(len(rows), 'valid PINs;', excluded, 'excluded;', len(refs), 'nearest branches')
