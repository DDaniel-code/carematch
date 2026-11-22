"""Verification call plan for one service: who to phone first, and what each confirmed facility adds.

    python -m scripts.call_plan --service c_section --radius 50 --budget 10

Writes (see docs/call_plan.md for definitions):
  analysis/<service>_call_candidates.csv      A: every candidate, evidence leads with column + quote, call questions
  analysis/<service>_data_check.csv           candidates held back for data checks (location / identity / branch)
  analysis/<service>_call_plan.csv            B: greedy order, new PIN ids per call, marginal and cumulative gain
  analysis/<service>_call_plan_baseline.csv   B: greedy vs "top-K by individual gain" vs upper bound, K = 3, 5, 10
  analysis/<service>_call_plan_if_first_fails.csv   demo: first facility says no -> re-plan without it
  analysis/<service>_call_plan_need.csv       c_section only: the same greedy plan counting only PINs in districts whose
                                              NFHS-5 caesarean rate is below 10% (where a confirmed facility matters most)
  analysis/<service>_pin_status.csv           one row per PIN for the map (covered now / newly covered at rank r)
  analysis/<service>_call_plan_summary.json
"""
import argparse
import csv
import json
import os
import sys
import statistics
import time
from collections import Counter

from carematch import datasource
from carematch.calls import (LOW_CSECTION_TARGET_PCT, candidates, current_coverage, greedy_plan, need_target, pin_need,
                             pin_universe, topk_baseline, upper_bound)
from carematch.recommend import CareIndex

OUT = 'analysis'
ASSUMPTION = 'assumes every selected facility confirms it provides the service'


def write(path, rows, fields):
    csv.field_size_limit(sys.maxsize)
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def candidate_row(c):
    return {**{k: v for k, v in c.items() if not k.startswith('_') and k not in ('leads', 'new_pins')},
            'lead_kinds': ' | '.join(k for k, _, _ in c['leads']),
            'lead_fields': ' | '.join(f for _, f, _ in c['leads']),
            'lead_quotes': ' | '.join(q.replace('|', '/') for _, _, q in c['leads']),
            'call_questions': ' | '.join(c['call_questions']),
            'data_flags': ' | '.join(c['data_flags']),
            'potential_new_pins': len(c.get('new_pins', ())) if 'new_pins' in c else ''}


def plan_rows(plan, pins, total_offices):
    out, offices = [], 0
    for r in plan:
        c = r['candidate']
        offices += sum(pins[p]['offices'] for p in r['new_pins'])
        out.append({'rank': r['rank'], 'facility_id': c['facility_id'], 'name': c['name'], 'branch': c['branch'],
                    'state': c['state'], 'lat': c['lat'], 'lon': c['lon'], 'phone': c['phone'],
                    'top_lead': f"{c['leads'][0][0]}: \"{c['leads'][0][2]}\" [{c['leads'][0][1]}]" if c['leads'] else '',
                    'new_pin_ids': ';'.join(sorted(r['new_pins'])), 'marginal_gain': r['marginal_gain'],
                    'cumulative_gain': r['cumulative_gain'], 'cumulative_share_of_pins': round(r['cumulative_gain'] / len(pins), 4),
                    'cumulative_share_of_post_offices': round(offices / total_offices, 4), 'assumption': ASSUMPTION})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--service', default='c_section')
    ap.add_argument('--radius', type=float, default=50)
    ap.add_argument('--budget', type=int, default=10)
    args = ap.parse_args()
    t = time.perf_counter()
    index = CareIndex.from_csv()
    pins, excluded = pin_universe(index)
    cov = current_coverage(index, args.service, args.radius, pins)
    cands, check = candidates(index, args.service, cov, args.radius)
    plan = greedy_plan(cands, args.budget)
    total_offices = sum(p['offices'] for p in pins.values())
    s = args.service
    os.makedirs(OUT, exist_ok=True)

    cfields = ['facility_id', 'name', 'branch', 'city', 'state', 'pin', 'lat', 'lon', 'location_confidence', 'phone',
               'phone_status', 'tier', 'beds', 'lead_count', 'lead_kinds', 'lead_fields', 'lead_quotes', 'potential_new_pins',
               'call_questions', 'data_flags']
    write(f'{OUT}/{s}_call_candidates.csv', [candidate_row(c) for c in cands], cfields)
    write(f'{OUT}/{s}_data_check.csv', [candidate_row(c) for c in check], cfields)

    pfields = ['rank', 'facility_id', 'name', 'branch', 'state', 'lat', 'lon', 'phone', 'top_lead', 'new_pin_ids',
               'marginal_gain', 'cumulative_gain', 'cumulative_share_of_pins', 'cumulative_share_of_post_offices', 'assumption']
    rows = plan_rows(plan, pins, total_offices)
    write(f'{OUT}/{s}_call_plan.csv', rows, pfields)
    fail = plan_rows(greedy_plan(cands, args.budget, exclude=[plan[0]['candidate']['facility_id']]), pins, total_offices) if plan else []
    write(f'{OUT}/{s}_call_plan_if_first_fails.csv', fail, pfields)

    base = []
    for k in (3, 5, 10):
        b = topk_baseline(cands, k)
        g = plan[min(k, len(plan)) - 1]['cumulative_gain'] if plan else 0
        ub = upper_bound(cands, k)
        base.append({'k': k, 'greedy_new_pins': g, 'topk_by_individual_gain_new_pins': b['unique_new_pins'],
                     'topk_sum_of_individual_gains': b['sum_individual_gains'], 'upper_bound': ub,
                     'greedy_share_of_upper_bound': round(g / ub, 3) if ub else None,
                     'topk_facility_ids': ';'.join(b['facility_ids']), 'denominator_pins': len(pins),
                     'uncovered_before': len(pins) - len(cov['covered']), 'assumption': ASSUMPTION})
    write(f'{OUT}/{s}_call_plan_baseline.csv', base, list(base[0]))

    # Need-targeted plan: the same candidates and greedy rule, counting only PINs in low-caesarean districts.
    need = pin_need(pins, datasource.load_nfhs()) if s == 'c_section' else {}
    target = need_target(need)
    need_summary = None
    if target:
        need_plan = greedy_plan(cands, args.budget, target=target)
        nrows = plan_rows(need_plan, pins, total_offices)
        for row, r in zip(nrows, need_plan):
            rates = [need[p] for p in r['new_pins']]
            top = Counter(pins[p]['district'].title() for p in r['new_pins']).most_common(3)
            row.update(other_new_pins=len(r['other_new_pins']), median_district_csection_pct=round(statistics.median(rates), 1),
                       districts=' | '.join(f'{d} {n}' for d, n in top))
        write(f'{OUT}/{s}_call_plan_need.csv', nrows, pfields + ['other_new_pins', 'median_district_csection_pct', 'districts'])
        known = [need[p] for r in plan for p in r['new_pins'] if need[p] is not None]
        need_summary = {
            'target': f'PINs in districts with an NFHS-5 caesarean rate below {LOW_CSECTION_TARGET_PCT:g}%',
            'threshold_pct': LOW_CSECTION_TARGET_PCT, 'pins_with_nfhs_match': sum(v is not None for v in need.values()),
            'target_pins': len(target), 'target_pins_uncovered_now': len(target - cov['covered']),
            'coverage_plan_median_district_csection_pct': round(statistics.median(known), 1) if known else None,
            'by_budget': [{'k': k,
                           'coverage_plan_target_pins': len(set().union(*(r['new_pins'] for r in plan[:k])) & target),
                           'need_plan_target_pins': need_plan[min(k, len(need_plan)) - 1]['cumulative_gain'] if need_plan else 0,
                           'need_plan_all_pins': len(set().union(*(r['new_pins'] | r['other_new_pins'] for r in need_plan[:k])))}
                          for k in (3, 5, 10)],
            'plan': [{k: r[k] for k in ('rank', 'name', 'branch', 'state', 'marginal_gain', 'cumulative_gain',
                                        'median_district_csection_pct', 'districts')} for r in nrows],
        }

    rank_of = {p: r['rank'] for r in plan for p in r['new_pins']}
    status = []
    for p in sorted(pins):
        info, (km, tier, fid) = pins[p], cov['nearest'][p]
        status.append({'pin': p, 'lat': round(info['centre'][0], 5), 'lon': round(info['centre'][1], 5),
                       'district': info['district'], 'state': info['state'], 'reliable': True, 'post_offices': info['offices'],
                       'covered_now': p in cov['covered'], 'nearest_credible_km': km, 'nearest_credible_tier': tier,
                       'nearest_facility_id': fid, 'newly_covered_at_rank': rank_of.get(p, ''),
                       'district_csection_pct': '' if need.get(p) is None else need[p]})
    for p in excluded:
        info = index.gaz.pin_info(p)
        status.append({'pin': p, 'district': info['district'], 'state': info['state'], 'reliable': False})
    write(f'{OUT}/{s}_pin_status.csv', status, ['pin', 'lat', 'lon', 'district', 'state', 'reliable', 'post_offices',
                                                 'covered_now', 'nearest_credible_km', 'nearest_credible_tier',
                                                 'nearest_facility_id', 'newly_covered_at_rank', 'district_csection_pct'])

    summary = {
        'service': s, 'radius_km': args.radius, 'budget': args.budget, 'assumption': ASSUMPTION,
        'pins_total': len(pins) + len(excluded), 'pins_reliable_denominator': len(pins), 'pins_excluded_unreliable': len(excluded),
        'credible_facilities': cov['credible_facilities'], 'pins_covered_now': len(cov['covered']),
        'pins_uncovered_now': len(pins) - len(cov['covered']),
        'candidates': len(cands), 'candidates_needing_contact': sum(c['phone_status'] != 'ok' for c in cands),
        'candidates_with_positive_gain': sum(bool(c['new_pins']) for c in cands), 'held_for_data_check': len(check),
        'plan': [{k: r[k] for k in ('rank', 'name', 'marginal_gain', 'cumulative_gain')} for r in rows],
        'baseline': [{k: b[k] for k in ('k', 'greedy_new_pins', 'topk_by_individual_gain_new_pins', 'upper_bound')} for b in base],
        'if_first_fails': [{k: r[k] for k in ('rank', 'name', 'marginal_gain', 'cumulative_gain')} for r in fail[:3]],
        'need_plan': need_summary,
        'seconds': round(time.perf_counter() - t, 1),
    }
    with open(f'{OUT}/{s}_call_plan_summary.json', 'w') as fh:
        json.dump(summary, fh, indent=2)
    json.dump(summary, sys.stdout, indent=2)
    print()


if __name__ == '__main__':
    main()
