"""Evaluate the optional preference model on the golden queries, against the default ranking.

Usage: python -m scripts.run_pref_eval
Outputs: eval/preference_results.csv (one row per query x variant), eval/preference_summary.json.
Exit 1 if the default ranking changed versus eval/results.csv, a quality check fails, or the evidence gate /
abstention differs between default and any preference variant.
"""
import csv
import json
import statistics
import sys
import time

from carematch.recommend import CareIndex, recommend
from carematch.services import SERVICES

VARIANTS = {
    'default': None,
    'time_critical': {'urgency': 'time_critical'},
    'can_travel': {'urgency': 'can_travel'},
    'low_cost': {'cost': 'low_cost'},
    'time_critical+low_cost': {'urgency': 'time_critical', 'cost': 'low_cost'},
}


def main():
    queries = list(csv.DictReader(open('eval/queries.csv', encoding='utf-8')))
    previous = {r['id']: r for r in csv.DictReader(open('eval/results.csv', encoding='utf-8'))}
    index = CareIndex.from_csv()
    for s in SERVICES:
        index.assessments(s)
    rows, stats, problems = [], {v: {'latency': []} for v in VARIANTS}, []
    base = {}
    for q in queries:
        for name, prefs in VARIANTS.items():
            t = time.perf_counter()
            r = recommend(index, q['service'], q['place'], preferences=prefs)
            stats[name]['latency'].append((time.perf_counter() - t) * 1000)
            res = r['results']
            if name == 'default':
                base[q['id']] = r
                old = previous.get(q['id'], {})
                if (res[0]['name'] if res else '') != old.get('top1_name', '') or \
                        '/'.join(c['tier'] for c in res) != old.get('tiers', ''):
                    problems.append(f"{q['id']}: default ranking changed versus eval/results.csv")
            b = base[q['id']]
            if bool(res) != bool(b['results']):
                problems.append(f"{q['id']} {name}: answered/abstained differs from default")
            if any(c['tier'] not in ('strong', 'moderate') for c in res):
                problems.append(f"{q['id']} {name}: weak evidence recommended")
            if not r['review']['passed']:
                problems.append(f"{q['id']} {name}: quality check failed "
                                + str([c['name'] for c in r['review']['checks'] if not c['passed']]))
            top, btop = (res[0] if res else None), (b['results'][0] if b['results'] else None)
            rows.append({
                'id': q['id'], 'service': q['service'], 'place': q['place'], 'place_type': q['place_type'], 'variant': name,
                'n_results': len(res), 'top1': top['name'] if top else '', 'top1_tier': top['tier'] if top else '',
                'top1_km': top['distance_km'] if top else '',
                'top1_score': top['preference']['score'] if top and 'preference' in top else '',
                'top1_cost': top.get('cost', {}).get('category', '') if top else '',
                'top1_cost_quote': (top.get('cost') or {}).get('quote') or '' if top else '',
                'top1_changed_vs_default': bool(top and btop and top['facility_id'] != btop['facility_id']),
                'top3': ' | '.join(f"{c['name']} ({c['distance_km']} km, {c['tier']})" for c in res),
                'cost_unknown_listed': len(r.get('cost_unknown_options', [])),
                'review_passed': r['review']['passed'],
            })
    summary = {'queries': len(queries), 'problems': problems, 'variants': {}}
    for name in VARIANTS:
        vr = [r for r in rows if r['variant'] == name]
        ans = [r for r in vr if r['n_results']]
        tops = [r['top1_km'] for r in ans]
        lat = sorted(stats[name]['latency'])
        summary['variants'][name] = {
            'answered': len(ans), 'quality_checks_passed': sum(r['review_passed'] for r in vr),
            'top1_changed_vs_default': sum(r['top1_changed_vs_default'] for r in vr),
            'median_top1_km': round(statistics.median(tops), 1) if tops else None,
            'top1_strong': sum(r['top1_tier'] == 'strong' for r in ans),
            'top1_cost_documented': sum(r['top1_cost'] in ('covered', 'insured') for r in ans),
            'queries_listing_cost_unknown_separately': sum(r['cost_unknown_listed'] > 0 for r in vr),
            'latency_ms_p50': round(lat[len(lat) // 2], 1), 'latency_ms_p95': round(lat[int(len(lat) * 0.95) - 1], 1),
        }
    with open('eval/preference_results.csv', 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open('eval/preference_summary.json', 'w') as fh:
        json.dump(summary, fh, indent=2)
    print(json.dumps(summary, indent=2))
    print('\nGATE', 'PASSED' if not problems else 'FAILED')
    sys.exit(0 if not problems else 1)


if __name__ == '__main__':
    main()
