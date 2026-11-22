"""Train and evaluate the C-section verification-lead model, and export leads for planners.

    python -m scripts.lead_model                 # reads data/*.csv, writes analysis/

Outputs:
  analysis/c_section_lead_model_metrics.json   sample sizes, held-out ROC-AUC / PR-AUC, baseline, controls
  analysis/c_section_lead_model_coefficients.csv
  analysis/c_section_leads.csv                 top 200 unlabeled facilities with reasons and cited facility text

Leads are for planner verification only: a high score means "looks like facilities that document C-section", never
"offers C-section".
"""
import argparse
import json
import os
import sys
import time
from collections import Counter

import numpy as np

from carematch import datasource
from carematch.lead_model import (BLOCK, SERVICE, USE_NOTE, baseline_scores, blocked, build_dataset, coefficients,
                                  cross_validate, leads, metrics)
from carematch.planner import write_csv
from carematch.recommend import CareIndex

OUT = 'analysis'


def by_region(data, scores, y=None):
    y = data['y'] if y is None else y
    out = {}
    for region in sorted(set(data['regions'])):
        idx = [i for i, r in enumerate(data['regions']) if r == region]
        out[region] = metrics([y[i] for i in idx], [scores[i] for i in idx], ks=(), min_positives=5)
    return out


def main(n_leads=200, C=0.3):
    started = time.perf_counter()
    facilities, pincodes, info = datasource.load()
    index = CareIndex(facilities, pincodes)
    data = build_dataset(index)
    leaked = [n for n in data['names'] if blocked(n)]
    if leaked:
        raise SystemExit(f'Feature names contain service vocabulary: {leaked}')

    y = np.asarray(data['y'])
    groups = Counter(data['groups'])
    sizes = {
        'facilities': len(y), 'proxy_positives_strong': int(y.sum()), 'unlabeled': int(len(y) - y.sum()),
        'unlabeled_by_tier': dict(Counter(t for t in data['tiers'] if t != 'strong')),
        'facility_groups': len(groups), 'groups_with_several_records': sum(1 for c in groups.values() if c > 1),
        'rows_assigned_to_their_group_region': data['rows_moved_to_group_region'],
        'features': len(data['names']),
        'by_region': {r: {'facilities': sum(1 for x in data['regions'] if x == r),
                          'groups': len({g for g, x in zip(data['groups'], data['regions']) if x == r}),
                          'proxy_positives': int(sum(y[i] for i, x in enumerate(data['regions']) if x == r))}
                      for r in sorted(set(data['regions']))},
    }

    oof, fold_model = cross_validate(data, C=C)
    base = baseline_scores(data)
    shuffled_runs = []
    for seed in range(5):
        shuffled = np.random.default_rng(seed).permutation(y)
        shuffled_runs.append(metrics(shuffled, cross_validate(data, labels=shuffled, C=C)[0]))
    shuffled_summary = {k: {'mean': round(float(np.mean([r[k] for r in shuffled_runs])), 3),
                            'min': min(r[k] for r in shuffled_runs), 'max': max(r[k] for r in shuffled_runs)}
                        for k in ('roc_auc', 'pr_auc')}
    shuffled_summary['runs'] = len(shuffled_runs)

    # Regularization was fixed at C=0.3 before looking at held-out results; this only shows how much it matters.
    sensitivity = {f'C={c}': {k: v for k, v in metrics(y, cross_validate(data, C=c)[0]).items() if k in ('roc_auc', 'pr_auc')}
                   for c in (0.03, 0.1, 0.3, 1.0, 3.0)}

    silver = [i for i, t in enumerate(data['tiers']) if t in ('moderate', 'none')]
    silver_y = [int(data['tiers'][i] == 'moderate') for i in silver]

    report = {
        'question': 'Which facilities look like those that document C-section, but do not? (verification leads)',
        'setup': {'service': SERVICE, 'proxy_positive': 'Strong C-section evidence tier', 'unlabeled': 'every other record',
                  'model': f'standardized logistic regression, class_weight=balanced, C={C}',
                  'validation': 'leave-one-region-out; each facility group (duplicates + same-name branches) kept in one fold',
                  'excluded_vocabulary_regex': BLOCK.pattern, 'use': USE_NOTE},
        'sample_sizes': sizes,
        'held_out': {
            'model': metrics(y, oof), 'baseline_hospital_then_specialties': metrics(y, base),
            'random_expected_pr_auc': round(float(y.mean()), 4),
            'model_by_region': by_region(data, oof), 'baseline_by_region': by_region(data, base),
        },
        'regularization_sensitivity': sensitivity,
        'controls': {
            'shuffled_labels_model': shuffled_summary,
            'documented_moderate_vs_no_evidence': {
                'note': 'Moderate records document C-section but were unlabeled in training; a useful model ranks them above records with no evidence',
                'model': metrics(silver_y, [oof[i] for i in silver], ks=()),
                'baseline': metrics(silver_y, [base[i] for i in silver], ks=())},
        },
        'source': info['source'], 'seconds': None,
    }
    coefs = coefficients(data, C=C)
    out_leads = leads(index, data, oof, fold_model, n=n_leads)
    report['leads_exported'] = len(out_leads)
    report['seconds'] = round(time.perf_counter() - started, 1)

    os.makedirs(OUT, exist_ok=True)
    with open(f'{OUT}/c_section_lead_model_metrics.json', 'w') as fh:
        json.dump(report, fh, indent=2)
    write_csv(coefs, f'{OUT}/c_section_lead_model_coefficients.csv')
    write_csv(out_leads, f'{OUT}/c_section_leads.csv')

    h = report['held_out']
    print(json.dumps({'sample_sizes': sizes, 'model': h['model'], 'baseline': h['baseline_hospital_then_specialties'],
                      'random_pr_auc': h['random_expected_pr_auc'], 'controls': report['controls']}, indent=2))
    print('\nBy held-out region (model | baseline):')
    for r in h['model_by_region']:
        m, b = h['model_by_region'][r], h['baseline_by_region'][r]
        print(f"  {r:10s} n={m['n']:5d} pos={m['positives']:3d}  ROC {m.get('roc_auc', '-')} PR {m.get('pr_auc', '-')}"
              f"  |  ROC {b.get('roc_auc', '-')} PR {b.get('pr_auc', '-')}")
    print('\nStrongest coefficients:', ', '.join(f"{c['feature']} {c['coefficient']:+}" for c in coefs[:12]))
    print('\nTop leads:')
    for lead in out_leads[:8]:
        print(f"  {lead['rank']}. {lead['name']} ({lead['city']}, {lead['state']}) score {lead['lead_score']} "
              f"tier {lead['current_c_section_tier']}\n     {lead['reasons']}\n     {lead['cited_text'][:220]}")
    print(f"\n{report['seconds']} s")


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--leads', type=int, default=200)
    p.add_argument('--C', type=float, default=0.3)
    a = p.parse_args()
    main(a.leads, a.C)
