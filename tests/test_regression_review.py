"""Regressions from the compatibility review in Sa1kyo121/carematch-india (docs/pr1_integration.md), ported with its fixes:

  - two same-name branches equally far from the patient are different facilities, not one duplicate;
  - a "not available" statement in another listing of the same facility stays visible and caps the tier;
  - column-shifted source rows are quarantined before anything is located or assessed.
"""
import unittest

from carematch.recommend import CareIndex, recommend
from carematch.review import review
from carematch.textutil import audit_source_rows
from tests.test_geo_recommend import PINS, STRONG_DIALYSIS, fac


class SpatialDeduplication(unittest.TestCase):
    def test_concurrent_first_searches_build_one_assessment(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from carematch.evidence import assess

        rows = [fac('a', 'Dialysis unit', 'Patna', 'Bihar', '', 25.6, 85.14, **STRONG_DIALYSIS)]
        index = CareIndex(rows, PINS)
        with patch('carematch.recommend.assess', wraps=assess) as observed:
            with ThreadPoolExecutor(max_workers=4) as workers:
                answers = list(workers.map(index.assessments, ['dialysis'] * 8))
        self.assertEqual(observed.call_count, len(rows))
        self.assertTrue(all(answer is answers[0] for answer in answers))
        self.assertEqual(set(index._assessed), {'dialysis'})

    def test_equidistant_same_name_branches_are_not_duplicates(self):
        # 11 km north and 11 km south of the patient: the same distance, 22 km apart, different PIN codes.
        rows = [fac('a', 'General Hospital', 'Patna', 'Bihar', '', 25.7, 85.14, **STRONG_DIALYSIS),
                fac('b', 'General Hospital', 'Patna', 'Bihar', '', 25.5, 85.14, **STRONG_DIALYSIS)]
        result = recommend(CareIndex(rows, PINS), 'dialysis', '25.6, 85.14')
        self.assertEqual({c['facility_id'] for c in result['results']}, {'a', 'b'})
        self.assertFalse(any('possible_duplicate_listing' in c['flags'] for c in result['results']))
        self.assertTrue(result['review']['passed'], result['review'])

    def test_equidistant_branches_stay_apart_in_nearest_and_price_orders(self):
        rows = [fac('a', 'General Hospital', 'Patna', 'Bihar', '', 25.7, 85.14, **STRONG_DIALYSIS),
                fac('b', 'General Hospital', 'Patna', 'Bihar', '', 25.5, 85.14, **STRONG_DIALYSIS)]
        index = CareIndex(rows, PINS)
        for mode in ('nearest', 'price'):
            result = recommend(index, 'dialysis', '25.6, 85.14', sort_mode=mode)
            self.assertEqual({c['facility_id'] for c in result['results']}, {'a', 'b'}, mode)
            self.assertTrue(result['review']['passed'], (mode, result['review']))

    def test_real_duplicates_are_still_merged(self):
        rows = [fac('a', 'Alpha Hospital', 'Patna', 'Bihar', '800001', 25.61, 85.14, **STRONG_DIALYSIS),
                fac('b', 'Alpha Hospital', 'Patna', 'Bihar', '800001', 25.611, 85.14, **STRONG_DIALYSIS)]
        result = recommend(CareIndex(rows, PINS), 'dialysis', '25.6, 85.14')
        self.assertEqual(len(result['results']), 1)
        self.assertIn('possible_duplicate_listing', result['results'][0]['flags'])
        self.assertEqual(result['results'][0]['merged_ids'], ['b'])

    def test_review_fails_when_one_facility_is_listed_twice(self):
        rows = [fac('a', 'Alpha Hospital', 'Patna', 'Bihar', '800001', 25.61, 85.14, **STRONG_DIALYSIS)]
        index = CareIndex(rows, PINS)
        result = recommend(index, 'dialysis', '25.6, 85.14', review=False)
        result['results'] = [result['results'][0], dict(result['results'][0], rank=2)]
        failed = [c['name'] for c in review(index, result)['checks'] if not c['passed']]
        self.assertIn('No facility listed twice', failed)


class NegativeEvidenceInDuplicates(unittest.TestCase):
    ROWS = [fac('a', 'Alpha Hospital', 'Patna', 'Bihar', '800001', 25.61, 85.14, **STRONG_DIALYSIS),
            fac('b', 'Alpha Hospital', 'Patna', 'Bihar', '800001', 25.611, 85.14, procedure=['No dialysis available'])]

    def test_negative_duplicate_is_visible_and_caps_the_tier(self):
        result = recommend(CareIndex(self.ROWS, PINS), 'dialysis', '25.6, 85.14')
        self.assertEqual(len(result['results']), 1)
        card = result['results'][0]
        self.assertEqual(card['tier'], 'moderate')
        self.assertIn('contradictory_claims', card['flags'])
        negative = next(e for e in card['evidence'] if e['kind'] == 'negative')
        self.assertEqual(negative['source_facility_id'], 'b')
        self.assertEqual(card['evidence'][0]['kind'], 'direct', 'the supporting quote stays first')
        self.assertEqual(card['evidence'][0]['source_facility_id'], 'a')
        self.assertTrue(result['review']['passed'], result['review'])

    def test_without_the_negative_listing_the_same_record_is_strong(self):
        result = recommend(CareIndex(self.ROWS[:1], PINS), 'dialysis', '25.6, 85.14')
        self.assertEqual(result['results'][0]['tier'], 'strong')
        self.assertTrue(all(e['kind'] != 'negative' for e in result['results'][0]['evidence']))

    def test_a_same_name_branch_elsewhere_does_not_contradict(self):
        far = fac('c', 'Alpha Hospital', 'Patna', 'Bihar', '', 25.9, 85.14, procedure=['No dialysis available'])
        result = recommend(CareIndex([self.ROWS[0], far], PINS), 'dialysis', '25.6, 85.14')
        card = next(c for c in result['results'] if c['facility_id'] == 'a')
        self.assertEqual(card['tier'], 'strong')
        self.assertNotIn('contradictory_claims', card['flags'])

    def test_a_carried_over_contradiction_never_moves_a_facility_up(self):
        # Two facilities at the same spot with the same own evidence; each has a second listing that contradicts it.
        # The one contradicted three times must not outrank the one contradicted once ("more evidence" tie-break).
        many = ['No dialysis available', 'Dialysis is not available', 'Dialysis not available here']
        rows = [fac('1x', 'Xray Hospital', 'Patna', 'Bihar', '800001', 25.61, 85.14, **STRONG_DIALYSIS),
                fac('1x-dup', 'Xray Hospital', 'Patna', 'Bihar', '800001', 25.61, 85.14, procedure=many[:1]),
                fac('2y', 'Yankee Hospital', 'Patna', 'Bihar', '800002', 25.61, 85.14, **STRONG_DIALYSIS),
                fac('2y-dup', 'Yankee Hospital', 'Patna', 'Bihar', '800002', 25.61, 85.14, procedure=many)]
        index = CareIndex(rows, PINS)
        by_id = {index.rows[i]['unique_id']: a for i, a in enumerate(index.assessments('dialysis'))}
        carried = lambda uid: sum(1 for e in by_id[uid]['evidence'] if e.get('source_facility_id'))
        self.assertGreater(carried('2y'), carried('1x'))
        result = recommend(index, 'dialysis', '25.6, 85.14')
        self.assertEqual([(c['facility_id'], c['tier']) for c in result['results']], [('1x', 'moderate'), ('2y', 'moderate')])


class SourceQuarantine(unittest.TestCase):
    def test_shifted_rows_are_quarantined(self):
        rows = [{'unique_id': 'normal', 'specialties': '["cardiology"]'},
                {'unique_id': '""",null,null,null,', 'specialties': 'null'},
                {'unique_id': 'Our clinic provides comprehensive solutions for acne',
                 'specialties': '{"coordinates":[80.98,26.88],"type":"Point"}'},
                {'unique_id': 'Equipped with dental technology', 'specialties': '107'}]
        accepted, rejected = audit_source_rows(rows)
        self.assertEqual(accepted, rows[:1])
        self.assertEqual(len(rejected), 3)
        self.assertTrue(all(r['reason'] == 'specialties_not_json_string_array' for r in rejected))
        self.assertEqual(rejected[2]['unique_id_raw'], 'Equipped with dental technology')

    def test_missing_or_empty_specialties_are_allowed(self):
        rows = [{'specialties': None}, {'specialties': ''}, {'specialties': '[]'}, {'unique_id': 'no such column'},
                {'specialties': '["a", null]'}]
        accepted, rejected = audit_source_rows(rows)
        self.assertEqual(accepted, rows)
        self.assertFalse(rejected)

    def test_index_reports_and_excludes_quarantined_rows(self):
        valid = fac('a', 'Alpha Hospital', 'Patna', 'Bihar', '800001', 25.61, 85.14, specialties=['nephrology'],
                    **STRONG_DIALYSIS)
        bad = dict(valid, unique_id='shifted prose', specialties='107')
        index = CareIndex([valid, bad], PINS)
        self.assertEqual(index.data_quality, {'input_rows': 2, 'accepted_rows': 1, 'quarantined_rows': 1})
        self.assertEqual(len(index.rows), 1)
        self.assertEqual(index.quarantine, audit_source_rows([valid, bad])[1])
        result = recommend(index, 'dialysis', 'Patna')
        self.assertEqual(result['data_quality']['quarantined_rows'], 1)
        self.assertEqual([c['facility_id'] for c in result['results']], ['a'])


if __name__ == '__main__':
    unittest.main()
