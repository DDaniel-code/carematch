"""Run evidence tiering over the full facilities export and print counts + review samples.

Usage: python -m scripts.calibrate_evidence [data/facilities.csv] [--samples N] [--service KEY]
"""
import argparse
import csv
import random
import sys
from collections import Counter, defaultdict

from carematch.evidence import TIERS, assess
from carematch.services import SERVICES


def load(path):
    csv.field_size_limit(sys.maxsize)
    with open(path, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path', nargs='?', default='data/facilities.csv')
    ap.add_argument('--samples', type=int, default=4)
    ap.add_argument('--service', default=None)
    ap.add_argument('--seed', type=int, default=7)
    args = ap.parse_args()
    rows = load(args.path)
    rng = random.Random(args.seed)
    services = [args.service] if args.service else list(SERVICES)
    print(f'{len(rows)} facilities\n')
    print(f"{'service':16}" + ''.join(f'{t:>10}' for t in TIERS) + f"{'neg':>6}{'indir':>7}  top flags")
    detail = {}
    for s in services:
        tiers, kinds, flags, by_tier = Counter(), Counter(), Counter(), defaultdict(list)
        for r in rows:
            a = assess(r, s)
            tiers[a['tier']] += 1
            kinds.update({e['kind'] for e in a['evidence']})
            flags.update(a['flags'])
            by_tier[a['tier']].append((r, a))
        print(f'{s:16}' + ''.join(f'{tiers[t]:>10}' for t in TIERS)
              + f"{kinds['negative']:>6}{kinds['indirect']:>7}  " + ', '.join(f'{k}:{v}' for k, v in flags.most_common(3)))
        detail[s] = by_tier
    for s in services:
        print(f'\n===== {s} =====')
        for t in ('strong', 'moderate', 'weak'):
            pool = detail[s][t]
            for r, a in rng.sample(pool, min(args.samples, len(pool))):
                print(f"[{t}] {r.get('name')} ({r.get('facilityTypeId')}, {r.get('address_city')}) — {'; '.join(a['reasons'])}"
                      + (f" flags={a['flags']}" if a['flags'] else ''))
                for e in a['evidence'][:3]:
                    print(f"      {e['kind']:8} {e['field']:11} {e['text'][:110]}")
        negs = [(r, e) for r, a in detail[s]['none'] + detail[s]['moderate'] + detail[s]['strong']
                for e in a['evidence'] if e['kind'] == 'negative']
        for r, e in rng.sample(negs, min(args.samples, len(negs))):
            print(f"[negative] {r.get('name')}: {e['field']} — {e['text'][:120]}")


if __name__ == '__main__':
    main()
