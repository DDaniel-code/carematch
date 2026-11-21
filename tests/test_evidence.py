import json
import unittest

from carematch.evidence import assess, classify_fragment
from carematch.services import resolve_service


def row(**fields):
    base = {'unique_id': 'u1', 'name': 'Test Hospital', 'facilityTypeId': 'hospital', 'capacity': 'null'}
    for k, v in fields.items():
        base[k] = json.dumps(v) if isinstance(v, list) else v
    return base


class ClassifyFragmentTests(unittest.TestCase):
    def test_direct_claim(self):
        self.assertEqual(classify_fragment('Provides hemodialysis', 'dialysis', 'procedure')[0], 'direct')

    def test_haemodialysis_spelling(self):
        self.assertEqual(classify_fragment('14 haemodialysis machines', 'dialysis', 'equipment')[0], 'direct')

    def test_negation_next_to_term(self):
        self.assertEqual(classify_fragment('No MRI facility on site', 'mri', 'capability')[0], 'negative')
        self.assertEqual(classify_fragment('Emergency services not available', 'emergency', 'capability')[0], 'negative')
        self.assertEqual(classify_fragment('Kidney failure cure without dialysis', 'dialysis', 'procedure')[0], 'negative')

    def test_unrelated_no_is_not_negation(self):
        self.assertEqual(classify_fragment('24x7 dialysis unit with no waiting time', 'dialysis', 'capability')[0], 'direct')
        self.assertEqual(classify_fragment('Performs cardiothoracic surgery up to closed heart', 'cardiac_surgery',
                                           'procedure')[0], 'direct')

    def test_outsourced_is_indirect(self):
        self.assertEqual(classify_fragment('MRI (via tie-up)', 'mri', 'equipment')[0], 'indirect')
        self.assertEqual(classify_fragment('MRI facility (outsourced)', 'mri', 'equipment')[0], 'indirect')

    def test_description_is_mention(self):
        self.assertEqual(classify_fragment('A hospital offering dialysis.', 'dialysis', 'description')[0], 'mention')

    def test_long_list_is_listed(self):
        frag = 'Departments include Cardiology, Urology, Nephrology, Dialysis, ENT, Orthopaedics'
        self.assertEqual(classify_fragment(frag, 'dialysis', 'capability')[0], 'listed')

    def test_false_positive_contexts_excluded(self):
        self.assertIsNone(classify_fragment('Gastric bypass surgery', 'cardiac_surgery', 'procedure'))
        self.assertIsNone(classify_fragment('Treatment for anxiety and burnout', 'burn', 'procedure'))
        self.assertIsNone(classify_fragment('Sun Burn Treatment', 'burn', 'procedure'))
        self.assertNotEqual((classify_fragment('Dental trauma management', 'trauma', 'procedure') or ('x',))[0], 'direct')

    def test_related_only(self):
        self.assertEqual(classify_fragment('Nephrology services', 'dialysis', 'procedure')[0], 'related')


class AssessTests(unittest.TestCase):
    def test_strong_needs_two_distinct_claims_in_two_columns(self):
        a = assess(row(procedure=['Provides hemodialysis'], equipment=['10 dialysis machines']), 'dialysis')
        self.assertEqual(a['tier'], 'strong')

    def test_same_sentence_in_two_columns_is_moderate(self):
        a = assess(row(equipment=['Burn care ward'], capability=['Burn care ward']), 'burn')
        self.assertEqual(a['tier'], 'moderate')

    def test_two_claims_plus_specialty_is_strong(self):
        a = assess(row(procedure=['Caesarean section', 'Emergency LSCS'], specialties=['gynecologyAndObstetrics']),
                   'c_section')
        self.assertEqual(a['tier'], 'strong')

    def test_specialty_only_is_weak(self):
        a = assess(row(specialties=['nephrology']), 'dialysis')
        self.assertEqual(a['tier'], 'weak')
        self.assertEqual(a['evidence'][0]['field'], 'specialties')

    def test_nothing_is_none(self):
        self.assertEqual(assess(row(procedure=['Root canal therapy']), 'dialysis')['tier'], 'none')

    def test_negative_only_is_none(self):
        a = assess(row(capability=['NICU facility not available']), 'nicu')
        self.assertEqual(a['tier'], 'none')
        self.assertIn('negative_claim', a['flags'])

    def test_contradiction_caps_at_moderate(self):
        a = assess(row(procedure=['MRI scans'], equipment=['1.5T MRI scanner'], capability=['No MRI facility']), 'mri')
        self.assertEqual(a['tier'], 'moderate')
        self.assertIn('contradictory_claims', a['flags'])

    def test_dentist_capped_at_weak(self):
        a = assess(row(facilityTypeId='dentist', procedure=['Provides dialysis'], equipment=['Dialysis machine']), 'dialysis')
        self.assertEqual(a['tier'], 'weak')
        self.assertIn('facility_type_mismatch', a['flags'])

    def test_excluding_is_negation(self):
        frag = 'General surgeries are performed excluding cardiothoracic and vascular surgery'
        self.assertEqual(classify_fragment(frag, 'cardiac_surgery', 'procedure')[0], 'negative')

    def test_specialty_name_capped(self):
        a = assess(row(name='Patra Dental Clinic', facilityTypeId='clinic',
                       procedure=['Emergency care 24x7'], capability=['Emergency service available 24 hours']), 'emergency')
        self.assertEqual(a['tier'], 'weak')
        self.assertIn('facility_type_mismatch', a['flags'])

    def test_specialty_word_in_hospital_name_not_capped(self):
        a = assess(row(name='City Eye and General Hospital', procedure=['Provides emergency care'],
                       capability=['24/7 emergency department']), 'emergency')
        self.assertEqual(a['tier'], 'strong')

    def test_small_clinic_capped_for_inpatient_service(self):
        a = assess(row(facilityTypeId='clinic', procedure=['NICU care'], equipment=['Neonatal intensive care unit']), 'nicu')
        self.assertEqual(a['tier'], 'moderate')
        self.assertIn('small_clinic_claim', a['flags'])

    def test_large_clinic_not_capped(self):
        a = assess(row(facilityTypeId='clinic', capacity='300', procedure=['NICU care'],
                       equipment=['Neonatal intensive care unit']), 'nicu')
        self.assertEqual(a['tier'], 'strong')

    def test_every_evidence_item_quotes_its_source_field(self):
        a = assess(row(procedure=['Provides hemodialysis'], description='A dialysis centre.'), 'dialysis')
        for e in a['evidence']:
            self.assertIn(e['field'], ('procedure', 'equipment', 'capability', 'description', 'specialties'))
            self.assertTrue(e['text'])
            self.assertTrue(e['evidence_id'].startswith('ev-'))


class ResolveServiceTests(unittest.TestCase):
    def test_resolve(self):
        self.assertEqual(resolve_service('Emergency C-section'), 'c_section')
        self.assertEqual(resolve_service('dialysis'), 'dialysis')
        self.assertEqual(resolve_service('NICU'), 'nicu')
        self.assertEqual(resolve_service('emergency'), 'emergency')
        self.assertEqual(resolve_service('CT scan'), 'ct_scan')
        self.assertIsNone(resolve_service('acupuncture'))


if __name__ == '__main__':
    unittest.main()
