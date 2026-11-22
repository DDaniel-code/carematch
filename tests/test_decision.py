import json
import unittest

from carematch.decision import cost_info, normalize_preferences, readiness
from carematch.recommend import CareIndex, recommend
from tests.test_geo_recommend import FACILITIES, MUZ, PINS, fac

STRONG = {'procedure': ['Provides hemodialysis'], 'equipment': ['10 dialysis machines']}
READY_FAR = fac('far1', 'Muz Kidney Institute', 'Muzaffarpur', 'Bihar', '842001', MUZ[0] + 0.02, MUZ[1],
                procedure=['Provides hemodialysis', 'Nephrologist available'],
                equipment=['12 dialysis machines'], capability=['Dialysis unit open 24x7'])
PUBLIC = dict(FACILITIES[1], operatorTypeId='public')          # Patna General: Moderate dialysis, public operator
ROWS = [FACILITIES[0], PUBLIC] + FACILITIES[2:] + [READY_FAR]


def dump(r):
    return json.dumps(r, sort_keys=True, default=str)


class DecisionUnitTests(unittest.TestCase):
    def test_preference_validation(self):
        self.assertFalse(normalize_preferences(None)['applied'])
        self.assertFalse(normalize_preferences({'urgency': 'default', 'cost': 'any'})['applied'])
        with self.assertRaises(ValueError):
            normalize_preferences({'urgency': 'yesterday'})

    def test_cost_categories_quote_the_record(self):
        self.assertEqual(cost_info({'operatorTypeId': 'public'})['category'], 'covered')
        c = cost_info({'capability': json.dumps(['Ayushman Bharat – PM-JAY empanelled hospital'])})
        self.assertEqual((c['category'], c['field']), ('covered', 'capability'))
        self.assertEqual(cost_info({'capability': json.dumps(['Offers cashless treatment'])})['category'], 'insured')
        self.assertEqual(cost_info({'capability': json.dumps(['Not empanelled under Ayushman Bharat'])})['category'], 'unknown')
        self.assertEqual(cost_info({})['category'], 'unknown')

    def test_readiness_signals_cite_quotes(self):
        r = readiness({'capability': json.dumps(['Blood bank on site', 'Anaesthesia team 24x7'])}, 'c_section')
        labels = {s['signal'] for s in r['found']}
        self.assertTrue({'blood bank / storage', 'anaesthesia', '24x7 service'} <= labels)
        self.assertIn('operation theatre', r['missing'])


class DecisionRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = CareIndex(ROWS, PINS)

    def test_default_is_unchanged(self):
        a = recommend(self.idx, 'dialysis', 'Patna')
        b = recommend(self.idx, 'dialysis', 'Patna', preferences={'urgency': 'default', 'cost': 'any'})
        self.assertEqual(dump(a), dump(b))
        self.assertNotIn('preference', a['results'][0])

    def test_time_critical_keeps_nearest_can_travel_goes_for_readiness(self):
        tc = recommend(self.idx, 'dialysis', 'Patna', preferences={'urgency': 'time_critical'})
        ct = recommend(self.idx, 'dialysis', 'Patna', preferences={'urgency': 'can_travel'})
        self.assertEqual(tc['results'][0]['name'], 'Patna Kidney Care')
        self.assertEqual(ct['results'][0]['name'], 'Muz Kidney Institute')     # ~60 km, Strong, 3/3 readiness signals
        for r in (tc, ct):
            self.assertTrue(r['review']['passed'], [c for c in r['review']['checks'] if not c['passed']])

    def test_low_cost_lists_unknown_cost_separately(self):
        r = recommend(self.idx, 'dialysis', 'Patna', preferences={'cost': 'low_cost'})
        self.assertEqual(r['results'][0]['name'], 'Patna General')               # public operator, Moderate
        self.assertEqual(r['results'][0]['cost']['category'], 'covered')
        unknown = {c['name'] for c in r['cost_unknown_options']}
        self.assertIn('Patna Kidney Care', unknown)                               # not scored as expensive, shown apart
        self.assertTrue(all('rank' not in c for c in r['cost_unknown_options']))
        self.assertTrue(r['review']['passed'])

    def test_evidence_gate_and_abstention_kept(self):
        for prefs in ({'urgency': 'time_critical'}, {'urgency': 'can_travel'}, {'cost': 'low_cost'}):
            r = recommend(self.idx, 'dialysis', 'Patna', preferences=prefs)
            self.assertTrue(all(c['tier'] in ('strong', 'moderate') for c in r['results']))
            self.assertNotIn('Patna Clinic', [c['name'] for c in r['results']])   # specialty-only = weak
            far = recommend(self.idx, 'dialysis', 'Mumbai', preferences=prefs)
            self.assertEqual(far['results'], [])                                  # nothing within 300 km stays a no
            self.assertIsNotNone(far['nearest_beyond'])

    def test_reasons_are_itemised_and_never_called_probability(self):
        r = recommend(self.idx, 'dialysis', 'Patna', preferences={'urgency': 'time_critical', 'cost': 'low_cost'})
        for c in r['results']:
            names = [x['name'] for x in c['preference']['components']]
            self.assertEqual(names, ['evidence', 'travel', 'readiness', 'cost'])
            self.assertAlmostEqual(sum(x['weight'] for x in c['preference']['components']), 1.0, places=6)
            self.assertNotIn('probab', c['why_ranked'].lower())
        self.assertIn('not', r['preference_model']['not_a_probability'])


if __name__ == '__main__':
    unittest.main()
