import unittest

from carematch.calls import (candidates, current_coverage, greedy_plan, need_target, pin_need, pin_universe, topk_baseline,
                             upper_bound)
from carematch.recommend import CareIndex
from tests.test_geo_recommend import FACILITIES, MUMBAI, MUZ, PATNA, PINS, fac

OBS = {'capability': ['Maternity ward and labour room', 'Obstetrics and Gynecology department'],
       'specialties': ['gynecologyAndObstetrics']}
EXTRA = [
    # credible C-section near Patna -> Patna PINs are covered now
    fac('cs1', 'Patna Women Hospital', 'Patna', 'Bihar', '800001', PATNA[0], PATNA[1],
        procedure=['Caesarean section', 'Emergency LSCS'], specialties=['gynecologyAndObstetrics']),
    # two candidates around Muzaffarpur (~60 km from Patna): they overlap completely
    fac('a1', 'Muz Maternity Hospital', 'Muzaffarpur', 'Bihar', '842001', MUZ[0], MUZ[1], **OBS),
    fac('a2', 'Muz City Hospital', 'Muzaffarpur', 'Bihar', '842002', MUZ[0] + 0.01, MUZ[1], **OBS),
    # a candidate in Mumbai with fewer leads: same individual gain, but no overlap with Muzaffarpur
    fac('c1', 'Mumbai Care Hospital', 'Mumbai', 'Maharashtra', '400001', MUMBAI[0], MUMBAI[1],
        capability=['Labour room']),
]
NO_PHONE = fac('np1', 'Muz No Phone Hospital', 'Muzaffarpur', 'Bihar', '842003', MUZ[0], MUZ[1] + 0.01, **OBS)
NO_PHONE['officialPhone'] = ''


class CallPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = CareIndex(FACILITIES + EXTRA + [NO_PHONE], PINS)
        cls.cov = current_coverage(cls.idx, 'c_section', 50)
        cls.cands, cls.check = candidates(cls.idx, 'c_section', cls.cov, 50)

    def test_universe_excludes_unreliable_pins(self):
        pins, excluded = pin_universe(self.idx)
        self.assertIn('800099', excluded)          # mis-geocoded centre was dropped
        self.assertNotIn('800099', pins)

    def test_current_coverage(self):
        self.assertTrue({p for p in self.cov['pins'] if p.startswith('8000')} <= self.cov['covered'])
        self.assertFalse({p for p in self.cov['pins'] if p.startswith('8420')} & self.cov['covered'])

    def test_candidates_carry_quotes_and_questions(self):
        ids = {c['facility_id'] for c in self.cands}
        self.assertTrue({'a1', 'a2', 'c1'} <= ids)
        self.assertNotIn('cs1', ids)               # already credible: verifying adds no coverage
        for c in self.cands:
            self.assertTrue(c['leads'] and c['call_questions'])
            for kind, field, quote in c['leads']:
                self.assertTrue(field and quote)

    def test_no_phone_is_listed_but_not_planned(self):
        np = next(c for c in self.cands if c['facility_id'] == 'np1')
        self.assertEqual(np['phone_status'], 'needs_contact')
        self.assertNotIn('np1', [r['candidate']['facility_id'] for r in greedy_plan(self.cands, 10)])

    def test_greedy_beats_topk_when_candidates_overlap(self):
        plan = greedy_plan(self.cands, 2)
        picked = [r['candidate']['facility_id'] for r in plan]
        self.assertIn('c1', picked)                # second call goes to a new area, not the overlapping twin
        base = topk_baseline(self.cands, 2)
        self.assertGreater(plan[-1]['cumulative_gain'], base['unique_new_pins'])
        self.assertLessEqual(plan[-1]['cumulative_gain'], upper_bound(self.cands, 2))

    def test_gains_add_up_and_stop_early(self):
        plan = greedy_plan(self.cands, 10)
        self.assertEqual(sum(r['marginal_gain'] for r in plan), plan[-1]['cumulative_gain'])
        self.assertTrue(all(r['marginal_gain'] > 0 for r in plan))
        self.assertLess(len(plan), 10)             # no positive gain left -> early stop
        union = set().union(*(r['new_pins'] for r in plan))
        self.assertEqual(len(union), plan[-1]['cumulative_gain'])

    def test_first_fails_replans_without_it(self):
        first = greedy_plan(self.cands, 3)[0]['candidate']['facility_id']
        again = greedy_plan(self.cands, 3, exclude=[first])
        self.assertNotIn(first, [r['candidate']['facility_id'] for r in again])

    def test_need_target_sends_the_first_call_where_need_is(self):
        # NFHS: caesareans are rare in Muzaffarpur and common in Mumbai. Mumbai's district has no reliable PIN centre
        # problem here, so both candidates' PINs are in the universe.
        nfhs = [{'district_name': 'Muzaffarpur', 'state_ut': 'Bihar', 'births_delivered_by_csection_5y_pct': '4.0'},
                {'district_name': 'Mumbai', 'state_ut': 'Maharashtra', 'births_delivered_by_csection_5y_pct': '35.0'},
                {'district_name': 'Patna', 'state_ut': 'Bihar', 'births_delivered_by_csection_5y_pct': '(8.0)'}]
        need = pin_need(self.cov['pins'], nfhs)
        self.assertEqual(need['842001'], 4.0)
        self.assertEqual(need['800001'], 8.0)                      # a small-sample value in parentheses is still read
        target = need_target(need)
        self.assertTrue(all(p.startswith('8') for p in target))    # no Mumbai PIN is a target
        plan = greedy_plan(self.cands, 10, target=target)
        self.assertEqual([r['candidate']['facility_id'][0] for r in plan], ['a'])   # one Muzaffarpur call, then nothing to gain
        self.assertTrue(plan[0]['new_pins'] <= target)
        self.assertEqual(plan[0]['marginal_gain'], len(plan[0]['new_pins']))
        self.assertNotIn('c1', [r['candidate']['facility_id'] for r in plan])        # Mumbai adds no target PIN
        # Without a target the same call list reaches Mumbai too, and unknown need is never treated as high.
        self.assertIn('c1', [r['candidate']['facility_id'] for r in greedy_plan(self.cands, 10)])
        self.assertEqual(need_target({'x': None, 'y': 12.0, 'z': 9.9}), {'z'})

    def test_deterministic(self):
        a = [r['candidate']['facility_id'] for r in greedy_plan(self.cands, 5)]
        b = [r['candidate']['facility_id'] for r in greedy_plan(self.cands, 5)]
        self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
