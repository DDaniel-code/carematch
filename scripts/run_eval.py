"""Run the golden query set, compute automatic metrics and sensitivity, and write a human review sheet.

Usage: python -m scripts.run_eval [--queries eval/queries.csv] [--out eval]
Outputs:
  eval/results.csv       one row per query (top-1 details, review status, latency)
  eval/review_sheet.csv  top-1 quote per query with columns for the human judgement
  eval/summary.json      metrics + sensitivity
Exit code 1 if a hard gate fails (citation fidelity < 100%, duplicate in top 3, any quality check failing).
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time

from carematch.recommend import CareIndex, recommend
from carematch.services import SERVICES, resolve_service

VARIANTS = {
    'bands_20_60_120_250': {'bands': (20, 60, 120, 250)},
    'bands_30_90_180_350': {'bands': (30, 90, 180, 350)},
    'strong_needs_3_claims': {'strong_min_claims': 3},
}


def top_ids(r):
    return [c['facility_id'] for c in r.get('results', [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--queries', default='eval/queries.csv')
    ap.add_argument('--out', default='eval')
    args = ap.parse_args()
    with open(args.queries, newline='', encoding='utf-8') as fh:
        queries = list(csv.DictReader(fh))

    t = time.time()
    index = CareIndex.from_csv()
    for s in SERVICES:
        index.assessments(s)
    warm_s = time.time() - t

    rows, latencies, base = [], [], {}
    for q in queries:
        t = time.perf_counter()
        r = recommend(index, q['service'], q['place'])
        latencies.append((time.perf_counter() - t) * 1000)
        base[q['id']] = r
        if 'error' in r:
            rows.append({**q, 'error': r['error']})
            continue
        top = r['results'][0] if r['results'] else None
        alt = r['farther_stronger'] or r['nearest_beyond']
        failed = [c['name'] for c in r['review']['checks'] if not c['passed']]
        rows.append({
            **q, 'resolved': r['origin']['label'], 'resolved_kind': r['origin']['kind'],
            'precision_km': r['origin']['precision_km'], 'band_km': r['band_km'] or '',
            'n_results': len(r['results']), 'tiers': '/'.join(c['tier'] for c in r['results']),
            'top1_name': top['name'] if top else '', 'top1_tier': top['tier'] if top else '',
            'top1_km': top['distance_km'] if top else '', 'top1_location_confidence': top['location_confidence'] if top else '',
            'top1_quote': top['evidence'][0]['quote'] if top else '', 'top1_field': top['evidence'][0]['field'] if top else '',
            'top1_flags': ';'.join(top['flags']) if top else '',
            'extra': (f"{alt['name']} ({alt['distance_km']} km, {alt['tier']})" if alt else ''),
            'review_passed': r['review']['passed'], 'review_failed': ';'.join(failed),
            'latency_ms': round(latencies[-1], 2),
        })

    ok = [r for r in base.values() if 'error' not in r]
    n_quotes = sum(len(c['evidence']) for r in ok for c in r['results'])
    fidelity_fail = [r['service'] + '@' + r['origin']['label'] for r in ok
                     for c in r['review']['checks'] if c['name'].startswith('Every quote') and not c['passed']]
    dup_fail = [r['service'] + '@' + r['origin']['label'] for r in ok
                for c in r['review']['checks'] if c['name'] == 'No facility listed twice' and not c['passed']]
    answered = [r for r in ok if r['results']]
    tops = [c for r in ok for c in r['results']]
    by_type = {}
    for q, row in zip(queries, rows):
        d = by_type.setdefault(q['place_type'], {'queries': 0, 'answered': 0, 'top1_km': []})
        d['queries'] += 1
        if row.get('n_results'):
            d['answered'] += 1
            d['top1_km'].append(row['top1_km'])
    for d in by_type.values():
        d['median_top1_km'] = round(statistics.median(d['top1_km']), 1) if d['top1_km'] else None
        del d['top1_km']

    sensitivity = {}
    for name, params in VARIANTS.items():
        same_top1, jacc = 0, []
        for q in queries:
            b = base[q['id']]
            if 'error' in b:
                continue
            v = recommend(index, q['service'], q['place'], review=False, **params)
            a_ids, v_ids = set(top_ids(b)), set(top_ids(v))
            same_top1 += (top_ids(b)[:1] == top_ids(v)[:1])
            jacc.append(len(a_ids & v_ids) / len(a_ids | v_ids) if a_ids | v_ids else 1.0)
        sensitivity[name] = {'same_top1_share': round(same_top1 / len(ok), 3),
                             'mean_top3_jaccard': round(statistics.mean(jacc), 3)}

    lat = sorted(latencies)
    summary = {
        'queries': len(queries), 'errors': len(queries) - len(ok),
        'answered_within_300km': len(answered), 'honest_no_answer': len(ok) - len(answered),
        'quality_checks_all_passed': sum(r['review']['passed'] for r in ok),
        'citation_fidelity': {'quotes_checked': n_quotes, 'queries_failing': fidelity_fail},
        'duplicates_in_top3': dup_fail,
        'recommendations': len(tops),
        'tier_mix': {t: sum(c['tier'] == t for c in tops) for t in ('strong', 'moderate')},
        'location_confidence_mix': {k: sum(c['location_confidence'] == k for c in tops)
                                    for k in ('high', 'medium', 'approximate', 'low')},
        'by_place_type': by_type,
        'latency_ms': {'p50': round(lat[len(lat) // 2], 2), 'p95': round(lat[int(len(lat) * 0.95) - 1], 2)},
        'index_warm_seconds': round(warm_s, 1),
        'sensitivity_vs_baseline': sensitivity,
    }

    os.makedirs(args.out, exist_ok=True)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(args.out, 'results.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    review_path = os.path.join(args.out, 'review_sheet.csv')
    previous = {}
    if os.path.exists(review_path):   # keep judgements already entered for unchanged top-1 answers
        with open(review_path, newline='', encoding='utf-8') as fh:
            previous = {(r['id'], r['top1_name']): r for r in csv.DictReader(fh)}
    judge_cols = ['model_quote_supports', 'model_one_facility', 'model_note',
                  'human_quote_supports', 'human_one_facility', 'human_note']
    with open(review_path, 'w', newline='', encoding='utf-8') as fh:
        cols = ['id', 'service', 'place', 'top1_name', 'top1_tier', 'top1_km', 'top1_field', 'top1_quote', 'top1_flags']
        w = csv.DictWriter(fh, fieldnames=cols + judge_cols)
        w.writeheader()
        for r in rows:
            if r.get('top1_name'):
                prev = previous.get((r['id'], r['top1_name']), {})
                w.writerow({**{c: r.get(c, '') for c in cols}, **{c: prev.get(c, '') for c in judge_cols}})
    with open(os.path.join(args.out, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, indent=2)
    print(json.dumps(summary, indent=2))

    gate_ok = not fidelity_fail and not dup_fail and summary['quality_checks_all_passed'] == len(ok) and not summary['errors']
    print('\nGATE', 'PASSED' if gate_ok else 'FAILED')
    sys.exit(0 if gate_ok else 1)


if __name__ == '__main__':
    main()
