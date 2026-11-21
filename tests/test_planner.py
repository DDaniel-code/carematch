import random
import unittest

from carematch.planner import PointIndex, _weighted_median, match_nfhs, nfhs_number
from carematch.textutil import haversine_km


class PointIndexTest(unittest.TestCase):
    """The grid search must agree exactly with checking every point."""

    @classmethod
    def setUpClass(cls):
        rng = random.Random(7)
        cls.points = [(rng.uniform(8, 35), rng.uniform(69, 97), k) for k in range(400)]
        cls.queries = [(rng.uniform(6, 37), rng.uniform(68, 98)) for _ in range(200)]
        cls.index = PointIndex(cls.points)

    def test_nearest_matches_brute_force(self):
        for lat, lon in self.queries:
            d, k = self.index.nearest(lat, lon)
            best = min(self.points, key=lambda p: haversine_km((lat, lon), (p[0], p[1])))
            self.assertAlmostEqual(d, haversine_km((lat, lon), (best[0], best[1])), places=6)

    def test_within_matches_brute_force(self):
        for lat, lon in self.queries[:50]:
            for km in (25, 50, 150):
                expect = {p[2] for p in self.points if haversine_km((lat, lon), (p[0], p[1])) <= km}
                self.assertEqual(self.index.keys_within(lat, lon, km), expect)

    def test_empty_index(self):
        self.assertEqual(PointIndex([]).nearest(20, 80), (None, None))


class NfhsTest(unittest.TestCase):
    def test_number_parsing(self):
        self.assertEqual(nfhs_number('12.5 '), (12.5, False))
        self.assertEqual(nfhs_number('(29.5)'), (29.5, True))
        self.assertEqual(nfhs_number('*'), (None, False))
        self.assertEqual(nfhs_number(''), (None, False))

    def test_district_matching(self):
        nfhs = [{'district_name': 'Purbi Champaran ', 'state_ut': 'Bihar'},
                {'district_name': 'Mon', 'state_ut': 'Nagaland'},
                {'district_name': 'Aurangabad', 'state_ut': 'Maharashtra'}]
        keys = [('Mon', 'Nagaland'), ('Purbi Champaran', 'Bihar'), ('Purbi Champaram', 'Bihar'),
                ('Aurangabad', 'Bihar'), ('Kakinada', 'Andhra Pradesh')]
        mapping, how = match_nfhs(keys, nfhs)
        self.assertEqual(mapping[('Mon', 'Nagaland')]['district_name'], 'Mon')
        self.assertIn(('Purbi Champaram', 'Bihar'), mapping)          # close spelling within the same state
        self.assertNotIn(('Aurangabad', 'Bihar'), mapping)            # same name in another state must not match
        self.assertEqual(how, {'exact': 2, 'close_spelling': 1, 'unmatched': 2})


class WeightedMedianTest(unittest.TestCase):
    def test_weights(self):
        self.assertEqual(_weighted_median([(10, 1), (100, 5)]), 100)
        self.assertEqual(_weighted_median([(10, 5), (100, 1)]), 10)


if __name__ == '__main__':
    unittest.main()
