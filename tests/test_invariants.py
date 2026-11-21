"""Invariants every recommendation must satisfy (docs/system_design.md §8).

Runs on the synthetic fixture always, and on the real data when data/facilities.csv exists
(a few golden queries by default; all of eval/queries.csv with CAREMATCH_FULL_EVAL=1).
"""
import csv
import json
import os
import unittest

from carematch.recommend import CareIndex, recommend
from tests.test_geo_recommend import FACILITIES, PINS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'facilities.csv')


def check_invariants(test, index, service, place):
    a = recommend(index, service, place)
    b = recommend(index, service, place)
    test.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str),
                     f'non-deterministic output for {service} @ {place}')
    if 'error' in a:
        return a
    failed = [c for c in a['review']['checks'] if not c['passed']]
    test.assertFalse(failed, f'{service} @ {place}: {failed}')
    for c in a['results']:
        test.assertIn(c['tier'], ('strong', 'moderate'))
        test.assertTrue(c['distance_km'] is None or c['distance_km'] > 0)
    if not a['results']:
        test.assertIsNone(a['band_km'])
    return a


class SyntheticInvariants(unittest.TestCase):
    def test_fixture_queries(self):
        idx = CareIndex(FACILITIES, PINS)
        for service, place in (('dialysis', 'Patna'), ('dialysis', 'Mumbai'), ('dialysis', '842001'),
                               ('MRI', 'Patna'), ('NICU', '25.6, 85.1')):
            check_invariants(self, idx, service, place)

    def test_review_catches_a_fabricated_quote(self):
        idx = CareIndex(FACILITIES, PINS)
        r = recommend(idx, 'dialysis', 'Patna')
        r['results'][0]['evidence'][0]['verbatim'] = 'Performs heart transplants'
        from carematch.review import review
        rv = review(idx, r)
        self.assertFalse(rv['passed'])
        self.assertFalse(next(c for c in rv['checks'] if c['name'].startswith('Every quote'))['passed'])


@unittest.skipUnless(os.path.exists(DATA), 'real data export not present')
class RealDataInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = CareIndex.from_csv(DATA, os.path.join(ROOT, 'data', 'pincodes.csv'))

    def test_golden_queries(self):
        with open(os.path.join(ROOT, 'eval', 'queries.csv'), newline='', encoding='utf-8') as fh:
            queries = list(csv.DictReader(fh))
        if not os.environ.get('CAREMATCH_FULL_EVAL'):
            queries = [q for q in queries if q['id'] in ('q02', 'q07', 'q30', 'q37')]
        for q in queries:
            with self.subTest(q=q['id']):
                check_invariants(self, self.idx, q['service'], q['place'])


if __name__ == '__main__':
    unittest.main()
