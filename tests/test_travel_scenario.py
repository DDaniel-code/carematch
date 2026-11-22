import csv
import unittest
from pathlib import Path

from carematch.travel_scenario import arrival_share


class TravelScenarioTests(unittest.TestCase):
    def test_time_boundary_and_delay(self):
        self.assertEqual(arrival_share(30, 60, (30, 60), (1, 2)), .75)
        self.assertEqual(arrival_share(30, 60, (30, 60), (1, 2), 1), .25)
        self.assertEqual(arrival_share(0, 10, (40,), (1,), 11), 0)

    def test_published_pin_snapshot(self):
        directory = Path(__file__).resolve().parents[1] / 'analysis'
        def rows(name):
            with (directory / name).open(encoding='utf-8') as f:
                return list(csv.DictReader(f))
        pins = rows('travel_pins.csv')
        reliable = {p['pin'] for p in rows('c_section_pin_status.csv') if p['reliable'].lower() == 'true'}
        self.assertEqual(len(pins), len(reliable))
        self.assertEqual({p['pin'] for p in pins}, reliable)
        refs = {r['facility_id']: r for r in rows('travel_facilities.csv')}
        for p in pins:
            for t in ('strong', 'moderate'):
                ref = refs[p[t+'_id']]
                self.assertEqual(ref['tier'], t)
                self.assertTrue(ref['quote'])
                self.assertGreaterEqual(float(p[t+'_km']), 0)
