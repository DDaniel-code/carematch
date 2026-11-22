import unittest

from carematch.recommend import CareIndex, recommend
from carematch.strategy_compare import compare_strategies
from tests.test_price_sort import PINS, ROWS


class StrategyComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = CareIndex(ROWS, PINS)

    def test_preference_order_does_not_replace_the_standard_baseline(self):
        preferred = recommend(self.index, 'dialysis', 'Patna', preferences={'cost': 'low_cost'})
        compared = compare_strategies(self.index, 'dialysis', 'Patna', preferred)
        for opt in compared['options']:
            first = recommend(self.index, 'dialysis', 'Patna', sort_mode=opt['mode'])['results'][0]
            self.assertEqual(opt['facility_id'], first['facility_id'])
            self.assertIn(opt['citation']['quote'], [e['verbatim'] for e in first['evidence']])

    def test_abstention_has_no_fabricated_quote_or_distance(self):
        active = recommend(self.index, 'dialysis', 'Mumbai')
        comp = compare_strategies(self.index, 'dialysis', 'Mumbai', active)
        self.assertFalse(any(c['citation'] or c['distance_km'] for c in comp['options']))
        self.assertIsNone(comp['straight_line_difference_km'])
