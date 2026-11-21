"""District access-gap analysis for planners.

    python -m scripts.access_gaps            # reads data/*.csv, writes analysis/

Outputs:
  analysis/access_gaps_districts.csv   one row per district: distance to credible care per service, NFHS indicators
  analysis/priority_maternal.csv       far from credible C-section care AND NFHS caesarean rate < 5%
  analysis/priority_dialysis.csv       far from credible dialysis AND top-quarter raised blood sugar
  analysis/access_gaps_summary.json    national coverage per service, NFHS match rate, priority counts
"""
import json
import os
import sys
import time

from carematch import datasource
from carematch.planner import (FAR_SHARE, LOW_CSECTION_PCT, NEAR_KM, dialysis_priorities, district_table, gap_kind,
                               maternal_priorities, write_csv)
from carematch.recommend import CareIndex
from carematch.services import SERVICES

OUT = 'analysis'


def main():
    started = time.perf_counter()
    facilities, pincodes, info = datasource.load()
    nfhs = datasource.load_nfhs()
    index = CareIndex(facilities, pincodes)
    services = list(SERVICES)
    table, match, national = district_table(index, services, nfhs)
    os.makedirs(OUT, exist_ok=True)
    write_csv(table, f'{OUT}/access_gaps_districts.csv')

    maternal = maternal_priorities(table)
    dialysis = dialysis_priorities(table)
    for r in maternal + dialysis:
        r['gap_kind'] = gap_kind(r)
    m_fields = ['district', 'state', 'c_section_median_km', 'c_section_share_far', 'c_section_credible_within_50km',
                'hospitals_listed_within_50km', 'csection_pct', 'csection_pct_small_sample', 'institutional_birth_pct',
                'gap_kind', 'post_offices']
    d_fields = ['district', 'state', 'dialysis_median_km', 'dialysis_share_far', 'dialysis_credible_within_50km',
                'hospitals_listed_within_50km', 'high_sugar_women_pct', 'high_sugar_men_pct', 'gap_kind', 'post_offices']
    if maternal:
        write_csv(maternal, f'{OUT}/priority_maternal.csv', m_fields)
    if dialysis:
        write_csv(dialysis, f'{OUT}/priority_dialysis.csv', d_fields)

    summary = {
        'definitions': {
            'unit': 'India Post PIN areas with a reliable centre, weighted by number of post offices',
            'far': f'more than {NEAR_KM} km straight-line from the nearest facility with Strong or Moderate evidence',
            'access_gap_district': f'at least {FAR_SHARE:.0%} of the district\'s post offices are far',
            'maternal_priority': f'access gap for C-section AND NFHS-5 caesarean rate below {LOW_CSECTION_PCT:g}% (WHO unmet-need signal)',
            'dialysis_priority': 'access gap for dialysis AND top-quarter share of adults with raised blood sugar (NFHS-5)',
        },
        'districts': len(table), 'nfhs_match': match, 'national_coverage': national,
        'priority_counts': {'maternal': len(maternal), 'dialysis': len(dialysis),
                            'maternal_by_gap_kind': {k: sum(1 for r in maternal if r['gap_kind'] == k)
                                                     for k in {r['gap_kind'] for r in maternal}}},
        'source': info['source'], 'seconds': round(time.perf_counter() - started, 1),
    }
    with open(f'{OUT}/access_gaps_summary.json', 'w') as fh:
        json.dump(summary, fh, indent=2)
    json.dump(summary, sys.stdout, indent=2)
    print()
    print('\nTop maternal priorities:')
    for r in maternal[:12]:
        print(f"  {r['district']}, {r['state']}: median {r['c_section_median_km']} km, {r['c_section_share_far']:.0%} far, "
              f"C-section {r['csection_pct']}%, inst. births {r['institutional_birth_pct']}%, "
              f"{r['hospitals_listed_within_50km']} hospitals listed <50 km -> {r['gap_kind']}")
    print('\nTop dialysis priorities:')
    for r in dialysis[:10]:
        print(f"  {r['district']}, {r['state']}: median {r['dialysis_median_km']} km, {r['dialysis_share_far']:.0%} far, "
              f"high sugar {r['_sugar']}%, {r['hospitals_listed_within_50km']} hospitals listed <50 km -> {r['gap_kind']}")


if __name__ == '__main__':
    main()
