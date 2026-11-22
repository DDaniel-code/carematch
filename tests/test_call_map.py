"""Verify published PIN identities for the normal and failed-first-call views."""
import csv
from pathlib import Path
import unittest

from carematch.call_map import load_map


ANALYSIS = Path(__file__).resolve().parents[1] / 'analysis'


class CallMapTest(unittest.TestCase):
    def test_budgeted_highlights(self):
        for failed in (False, True):
            points, calls, _ = load_map(ANALYSIS, first_failed=failed)
            name = 'c_section_call_plan_if_first_fails.csv' if failed else 'c_section_call_plan.csv'
            with (ANALYSIS / name).open(encoding='utf-8-sig', newline='') as source:
                published = list(csv.DictReader(source))
            for budget in (0, 3, 5, 10):
                slots = max(0, budget - int(failed))
                expected = {pin for row in published[:slots] for pin in row['new_pin_ids'].split(';') if pin}
                actual = {p['pin'] for p in points if 0 < p['rank'] <= slots}
                with self.subTest(failed=failed, budget=budget):
                    self.assertEqual(actual, expected)
                    self.assertEqual(len(actual), int(calls[:slots][-1]['cumulative_gain']) if calls[:slots] else 0)
