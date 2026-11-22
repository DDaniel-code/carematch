"""Reproduce the comparison for the golden queries and validate every displayed citation."""
import csv
import json
from collections import Counter
from pathlib import Path

from carematch.recommend import CareIndex, recommend
from carematch.strategy_compare import compare_strategies
from carematch.textutil import fragments


def main():
    path = Path(__file__).resolve().parents[1] / 'eval'
    index = CareIndex.from_csv()
    totals = Counter()
    reports = []
    with (path / 'queries.csv').open(encoding='utf-8') as source:
        for q in csv.DictReader(source):
            service, place = q['service'], q['place']
            base = recommend(index, service, place)
            comparison = compare_strategies(index, service, place, base)
            totals['queries'] += 1
            totals['different_first_for_distance'] += comparison['top_changed']
            for option in comparison['options']:
                assert option['reason'] != 'Comparison unavailable for this order.', (q['id'], option)
                if option['mode'] == 'price':
                    totals['price_' + (option['price_basis'] or 'no_rank')] += 1
                if option['facility_id']:
                    rows = [index.rows[i] for i in index.by_id[str(option['facility_id'])]]
                    assert option['citation'], (q['id'], option['facility_id'])
                    for cite in (option['citation'], option['price_citation']):
                        if cite:
                            assert any(cite['quote'] in str(row.get(cite['field'], '')) or
                                       any(cite['quote'] in s for s in fragments(row.get(cite['field'])))
                                       for row in rows), (q['id'], cite)
                            totals['citations_verified'] += 1
            reports.append(dict(id=q['id'], service=service, place=place, **comparison))
    with (path / 'strategy_comparisons.json').open('w', encoding='utf-8') as f:
        json.dump({'totals': dict(totals), 'queries': reports}, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(dict(totals))


if __name__ == '__main__':
    main()
