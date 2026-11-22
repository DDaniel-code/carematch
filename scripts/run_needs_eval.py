"""Evaluate the need lexicon on eval/needs_queries.csv and write eval/needs_summary.json.

Usage: python -m scripts.run_needs_eval
The phrases were written by the team, so this measures lexicon coverage, not accuracy on real user input.
"""
import csv
import json
import sys
from collections import Counter

from carematch.needs import interpret_need


def main():
    with open('eval/needs_queries.csv', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    by_lang, misses = Counter(), []
    correct = Counter()
    for r in rows:
        x = interpret_need(r['text'])
        checks = {'status': x['status'] == r['expected_status'],
                  'service': (x['service'] or '') == r['expected_service'],
                  'urgency': (x['urgency'] or '') == r['expected_urgency'],
                  'red_flag': str(x['red_flag']) == r['expected_red_flag']}
        correct.update(k for k, ok in checks.items() if ok)
        by_lang[(r['language'], all(checks.values()))] += 1
        if not all(checks.values()):
            misses.append({'id': r['id'], 'text': r['text'], 'got': [x['status'], x['service'], x['urgency'], x['red_flag']]})
    n = len(rows)
    summary = {
        'phrases': n, 'note': 'phrases written by the team: measures lexicon coverage, not real-world accuracy',
        'accuracy': {k: round(correct[k] / n, 3) for k in ('status', 'service', 'urgency', 'red_flag')},
        'all_fields_correct': {lang: f"{by_lang[(lang, True)]}/{by_lang[(lang, True)] + by_lang[(lang, False)]}"
                               for lang in sorted({r['language'] for r in rows})},
        'expected_no_match': sum(r['expected_status'] == 'no_match' for r in rows),
        'expected_ambiguous': sum(r['expected_status'] == 'ambiguous' for r in rows),
        'misses': misses,
    }
    with open('eval/needs_summary.json', 'w') as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    sys.exit(0 if not misses else 1)


if __name__ == '__main__':
    main()
