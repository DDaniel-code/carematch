import csv
import os
import unittest

from carematch.needs import CONDITIONS, interpret_need
from carematch.services import SERVICES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NeedLexiconTests(unittest.TestCase):
    def test_lexicon_points_only_to_supported_services(self):
        self.assertEqual(len({c['id'] for c in CONDITIONS}), len(CONDITIONS))
        for c in CONDITIONS:
            self.assertIn(c['service'], SERVICES)
            for s in c['also']:
                self.assertIn(s, SERVICES)
            self.assertIn(c['urgency'], ('time_critical', 'default', 'can_travel'))

    def test_red_flag_puts_emergency_call_first(self):
        x = interpret_need('heavy bleeding after delivery, she fainted')
        self.assertEqual((x['status'], x['service'], x['urgency'], x['red_flag']), ('matched', 'c_section', 'time_critical', True))
        self.assertIn('108', x['call_now'])
        self.assertIn('not a diagnosis', x['disclaimer'])

    def test_quotes_come_from_the_users_words(self):
        for text in ('accident ho gaya sar par chot lagi hai', 'delivery ke baad khoon bahut beh raha hai',
                     'kidney failure patient needs dialysis'):
            x = interpret_need(text)
            self.assertTrue(x['matched'])
            for m in x['matched']:
                self.assertIn(m['phrase'], x['input'])

    def test_hindi_romanized(self):
        self.assertEqual(interpret_need('saanp ne kaat liya')['service'], 'emergency')
        self.assertEqual(interpret_need('ladki aag se jal gayi')['service'], 'burn')
        self.assertEqual(interpret_need('navjaat bachcha saans nahi le raha')['service'], 'nicu')  # "nahi" is part of the sign

    def test_negation_and_its_scope(self):
        self.assertEqual(interpret_need('not a burn just a rash')['status'], 'no_match')
        x = interpret_need('no bleeding but labour for 20 hours')
        self.assertEqual(x['service'], 'c_section')
        self.assertEqual([m['condition_id'] for m in x['matched']], ['obstructed_labour'])

    def test_bleeding_needs_pregnancy_context(self):
        self.assertNotEqual(interpret_need('bleeding from a cut on the hand')['service'], 'c_section')

    def test_false_friends(self):
        for text in ('heartburn after dinner', 'sunburn on face', 'fever and cough', 'need a good hospital', ''):
            self.assertEqual(interpret_need(text)['status'], 'no_match', text)

    def test_two_emergencies_need_confirmation(self):
        x = interpret_need('road accident and the pregnant passenger is bleeding')
        self.assertEqual(x['status'], 'ambiguous')
        self.assertIn('trauma', x['also_possible'])
        self.assertTrue(x['red_flag'])

    def test_specific_condition_beats_imaging_word(self):
        x = interpret_need('head injury needs CT')
        self.assertEqual((x['service'], x['urgency']), ('trauma', 'time_critical'))
        self.assertIn('ct_scan', x['also_possible'])
        self.assertEqual(interpret_need('CT scan advised for headache')['service'], 'ct_scan')

    def test_condition_notes(self):
        self.assertTrue(any('cath lab' in n for n in interpret_need('suspected heart attack')['notes']))

    def test_eval_set(self):
        with open(os.path.join(ROOT, 'eval', 'needs_queries.csv'), encoding='utf-8') as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            with self.subTest(r['id']):
                x = interpret_need(r['text'])
                self.assertEqual(x['status'], r['expected_status'])
                self.assertEqual(x['service'] or '', r['expected_service'])
                self.assertEqual(x['urgency'] or '', r['expected_urgency'])
                self.assertEqual(str(x['red_flag']), r['expected_red_flag'])


if __name__ == '__main__':
    unittest.main()
