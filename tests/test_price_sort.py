import csv
import json
import os
import unittest

from carematch.price import classify, comparable, price_evidence, surely_cheaper
from carematch.recommend import CareIndex, recommend
from tests.test_geo_recommend import FACILITIES, PATNA, PINS, fac

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'facilities.csv')
DIAL = {'procedure': ['Provides hemodialysis'], 'equipment': ['10 dialysis machines']}


def dial(uid, name, dlat, price=None, **extra):
    claims = dict(DIAL)
    if price:
        claims['capability'] = [price]
    claims.update(extra)
    return fac(uid, name, 'Patna', 'Bihar', '800001', PATNA[0] + dlat, PATNA[1], **claims)


ROWS = FACILITIES[5:] + [   # keep the Mumbai / Muzaffarpur fixtures, replace the Patna dialysis ones
    dial('d3', 'Renal C', 0.004),                                                         # nearest, no price
    dial('d1', 'Renal A', 0.009, 'Dialysis Rs 1,500 per session'),
    dial('d4', 'Renal D', 0.018, 'Dialysis package Rs 15,000 per month'),                # different unit
    dial('d2', 'Renal B', 0.027, 'Dialysis charges Rs 900 to Rs 1,200 per session'),
    dial('d6', 'Renal Public', 0.012),                                                    # public operator, no price
    dial('d7', 'Renal Equip', 0.015, 'New dialysis machines worth Rs. 40 lakh'),         # capital cost
    dial('d5', 'Renal Far', 0.36, 'Dialysis Rs 700 per session'),                        # ~40 km: outside the budget
    dial('m1', 'Renal Mixed', 0.006, None, capability=[
        'Fortis Hospital offers kidney care', 'Fortis Hospital dialysis wing', 'Fortis Hospital nephrology team']),
    fac('cs_bad', 'Near Maternity', 'Patna', 'Bihar', '800002', PATNA[0] + 0.004, PATNA[1],
        procedure=['Caesarean section', 'Emergency LSCS'], capability=['Caesarean section not available at night']),
    fac('cs_ok', 'Safe Maternity', 'Patna', 'Bihar', '800002', PATNA[0] + 0.02, PATNA[1],
        procedure=['Caesarean section', 'Emergency LSCS'], specialties=['gynecologyAndObstetrics']),
] + [fac(f'pt{i}', f'Patna General {i}', 'Patna', 'Bihar', '800003', PATNA[0] + i * 0.01, PATNA[1] + 0.01,
         procedure=['General surgery']) for i in range(4)]
for r in ROWS:
    if r['unique_id'] == 'd6':
        r['operatorTypeId'] = 'public'


class PriceParserTests(unittest.TestCase):
    def test_bounds_units_conditions(self):
        k, d = classify('Offers dialysis services at concessional pricing (Rs. 350 or less per session) including blood tubing')
        self.assertEqual((k, d['bound'], d['amount_max_inr'], d['amount_min_inr'], d['unit']),
                         ('patient_price', 'upper_bound', 350, None, 'per_session'))
        self.assertIn('concessional / subsidised rate', d['conditions'])
        self.assertEqual(classify('Dialysis Rs 1,200 - 1,800 per session')[1]['bound'], 'range')
        self.assertEqual(classify('MRI scans starting at ₹2,500 per scan')[1]['bound'], 'lower_bound')

    def test_never_inferred(self):
        self.assertEqual(classify('New dialysis machines worth Rs. 40 lakh')[0], 'capital_or_equipment')
        self.assertEqual(classify('Dialysis ward built at a cost of ₹4.38 crore')[0], 'capital_or_equipment')
        self.assertEqual(classify('Covers up to INR 5 lakhs per family per year under PM-JAY')[0], 'insurer_coverage')
        self.assertEqual(price_evidence({'operatorTypeId': 'public', 'capability': json.dumps(['Dialysis unit'])}, 'dialysis'),
                         (None, []))                                                     # public is not free
        p = classify('Dialysis package Rs 15,000 per month')[1]
        self.assertNotEqual(p['unit'], 'per_session')                                    # package is not per session
        self.assertIsNone(price_evidence({'capability': json.dumps(['Health check package Rs 999'])}, 'dialysis')[0])

    def test_comparison_rules(self):
        up = {'scope': 'dialysis', 'unit': 'per_session', 'bound': 'upper_bound', 'amount_min_inr': None, 'amount_max_inr': 350}
        ex = {'scope': 'dialysis', 'unit': 'per_session', 'bound': 'exact', 'amount_min_inr': 500, 'amount_max_inr': 500}
        rg = {'scope': 'dialysis', 'unit': 'per_session', 'bound': 'range', 'amount_min_inr': 300, 'amount_max_inr': 600}
        pk = {'scope': 'dialysis', 'unit': 'package', 'bound': 'exact', 'amount_min_inr': 400, 'amount_max_inr': 400}
        self.assertTrue(surely_cheaper(up, ex))
        self.assertFalse(surely_cheaper(rg, ex))         # overlapping range is not surely cheaper
        self.assertFalse(comparable(ex, pk))             # different unit
        self.assertFalse(comparable(ex, dict(ex, unit='unspecified')))


class SortModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = CareIndex(ROWS, PINS)

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            recommend(self.idx, 'dialysis', 'Patna', sort_mode='cheapest')
        with self.assertRaises(ValueError):
            recommend(self.idx, 'dialysis', 'Patna', sort_mode='nearest', preferences={'urgency': 'time_critical'})
        with self.assertRaises(ValueError):
            recommend(self.idx, 'dialysis', 'Patna', sort_mode='price', max_extra_km=-1)

    def test_default_unchanged_except_additive_price_keys(self):
        r = recommend(self.idx, 'dialysis', 'Patna')
        self.assertEqual(r['sort_mode'], 'default')
        self.assertNotIn('sort', r)
        self.assertTrue(all('price_info' in c and 'price_context' in c for c in r['results']))

    def test_nearest_orders_by_distance_and_lists_unresolved(self):
        r = recommend(self.idx, 'dialysis', 'Patna', sort_mode='nearest')
        d = [c['distance_km'] for c in r['results']]
        self.assertEqual(d, sorted(d))
        self.assertNotIn('Renal Mixed', [c['name'] for c in r['results']])
        self.assertIn('Renal Mixed', [c['name'] for c in r['sort']['branch_unresolved']])
        self.assertTrue(r['review']['passed'], [c for c in r['review']['checks'] if not c['passed']])

    def test_nearest_emergency_safety(self):
        r = recommend(self.idx, 'C-section', f'{PATNA[0]}, {PATNA[1]}', sort_mode='nearest')
        near = next(c for c in r['results'] if c['name'] == 'Near Maternity')
        self.assertLess(near['distance_km'], r['results'][0]['distance_km'])           # nearer, but says "not available"
        self.assertEqual(r['results'][0]['name'], 'Safe Maternity')
        self.assertTrue(r['results'][0].get('safety_reordered'))
        self.assertTrue(r['sort']['safety_note'])
        self.assertTrue(r['review']['passed'])

    def test_price_mode_compares_only_same_unit_within_budget(self):
        r = recommend(self.idx, 'dialysis', 'Patna', sort_mode='price', max_extra_km=25)
        pc = r['sort']['price_comparison']
        self.assertEqual((pc['unit'], pc['ranked_by'], pc['comparable_quotes']), ('per_session', 'price', 2))
        self.assertEqual([c['name'] for c in r['results']], ['Renal B', 'Renal A'])      # 900-1,200 before 1,500
        self.assertTrue(pc['cheapest_claim'])                                             # 1,200 < 1,500, same conditions
        names = lambda key: [c['name'] for c in r['sort'][key]]
        self.assertIn('Renal C', names('price_unknown_nearby'))                          # unknown price stays visible
        self.assertIn('Renal Public', names('price_unknown_nearby'))                     # public is not free
        self.assertIn('Renal D', names('price_not_comparable'))                          # per month vs per session
        self.assertNotIn('Renal Far', [c['name'] for c in r['results']])                 # beyond nearest + 25 km
        equip = next(c for c in r['sort']['price_unknown_nearby'] if c['name'] == 'Renal Equip')
        self.assertEqual(equip['price_context'][0]['kind'], 'capital_or_equipment')
        self.assertTrue(r['review']['passed'], [c for c in r['review']['checks'] if not c['passed']])

    def test_single_quote_is_never_cheapest(self):
        r = recommend(self.idx, 'dialysis', 'Patna', sort_mode='price', max_extra_km=0.5)
        pc = r['sort']['price_comparison']
        self.assertLess(pc['comparable_quotes'], 2)
        self.assertEqual(pc['ranked_by'], 'distance')
        self.assertFalse(pc['cheapest_claim'])

    def test_abstention_kept(self):
        for mode in ('nearest', 'price'):
            r = recommend(self.idx, 'dialysis', 'Mumbai', sort_mode=mode)
            self.assertEqual(r['results'], [])
            self.assertIsNotNone(r['nearest_beyond'])


@unittest.skipUnless(os.path.exists(DATA), 'real data export not present')
class RealDataSortModes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = CareIndex.from_csv(DATA, os.path.join(ROOT, 'data', 'pincodes.csv'))

    def test_nagpur_dialysis_price(self):
        r = recommend(self.idx, 'dialysis', 'Nagpur', sort_mode='price')
        pc = r['sort']['price_comparison']
        self.assertTrue(r['results'])
        self.assertFalse(pc['cheapest_claim'])
        self.assertEqual(pc['ranked_by'], 'distance')
        w = next(c for c in r['sort']['branch_unresolved'] if c['name'].startswith('Wockhardt Hospital Nagpur'))
        self.assertEqual((w['price_info']['bound'], w['price_info']['amount_max_inr'], w['price_info']['unit']),
                         ('upper_bound', 350, 'per_session'))
        self.assertTrue(r['review']['passed'])

    def test_missing_price_keeps_options(self):
        r = recommend(self.idx, 'CT scan', 'Varanasi', sort_mode='price')
        self.assertEqual(r['sort']['price_comparison']['comparable_quotes'], 0)
        self.assertTrue(r['results'] and r['sort']['price_unknown_nearby'])
        self.assertTrue(all(c['price_info'] is None for c in r['results']))
        self.assertTrue(r['review']['passed'])

    def test_golden_queries_all_modes(self):
        with open(os.path.join(ROOT, 'eval', 'queries.csv'), encoding='utf-8') as fh:
            queries = list(csv.DictReader(fh))
        if not os.environ.get('CAREMATCH_FULL_EVAL'):
            queries = [q for q in queries if q['id'] in ('q02', 'q07', 'q16', 'q30', 'q37')]
        for q in queries:
            base = recommend(self.idx, q['service'], q['place'])
            for mode in ('nearest', 'price'):
                with self.subTest(q=q['id'], mode=mode):
                    r = recommend(self.idx, q['service'], q['place'], sort_mode=mode)
                    self.assertTrue(r['review']['passed'], [c for c in r['review']['checks'] if not c['passed']])
                    self.assertEqual(bool(r['results']), bool(base['results']))
                    self.assertTrue(all(c['tier'] in ('strong', 'moderate') for c in r['results']))


if __name__ == '__main__':
    unittest.main()
