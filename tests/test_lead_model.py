import json
import unittest
from types import SimpleNamespace

try:
    import numpy  # noqa: F401
    import sklearn  # noqa: F401
    HAVE_ML = True
except ImportError:
    HAVE_ML = False

from carematch.lead_model import (BLOCK, INDICATORS, SPECIALTY_FAMILIES, blocked, facility_features, facility_groups,
                                  feature_label, group_regions, specialty_family)

ROW = {
    'unique_id': 'A1', 'name': 'Sample General Hospital', 'facilityTypeId': 'hospital', 'operatorTypeId': 'private',
    'capacity': '120', 'numberDoctors': '35', 'yearEstablished': '1998', 'phone_numbers': '["+91 98765 43210"]',
    'officialWebsite': 'example.org', 'source_urls': '["https://a.example", "https://b.example"]',
    'engagement_metrics_n_followers': '2400',
    'specialties': '["generalSurgery", "internalMedicine", "pediatrics", "radiology", "dentistry"]',
    'procedure': '["Laparoscopic surgeries", "Cataract surgery"]',
    'equipment': '["8-bed ICU with ventilators", "CT scanner"]',
    'capability': '["24x7 emergency services", "Cashless treatment for insured patients"]',
    'description': 'A multi-speciality hospital in the city. It has an ambulance service.',
}

# Text that names the service or maternity care, in every field the model reads.
SERVICE_TEXT = {
    'specialties': ['gynecologyAndObstetrics', 'obstetricsAndMaternityCare', 'anesthesia', 'neonatologyPerinatalMedicine'],
    'procedure': ['Caesarean section (LSCS) performed', 'Normal and C-section deliveries', 'Labour room with 4 beds'],
    'equipment': ['Blood bank', 'NICU with 6 warmers', 'Anaesthesia workstation'],
    'capability': ['High-risk pregnancy care', 'Emergency obstetric care available 24x7', 'Maternity ward'],
}


def with_service_text(row):
    out = dict(row)
    for field, extra in SERVICE_TEXT.items():
        out[field] = json.dumps(json.loads(row[field]) + extra)
    out['description'] = row['description'] + ' Caesarean deliveries are performed by our obstetricians. We care for mothers.'
    return out


class NoServiceVocabularyTest(unittest.TestCase):
    def test_adding_service_text_changes_nothing(self):
        """The label is defined by C-section wording; no feature may see that wording."""
        plain, plain_cite = facility_features(ROW)
        loaded, loaded_cite = facility_features(with_service_text(ROW))
        self.assertEqual(plain, loaded)
        self.assertEqual(plain_cite, loaded_cite)

    def test_block_catches_label_vocabulary(self):
        for phrase in ('Caesarean section', 'cesarean', 'C-section', 'LSCS', 'CEmONC', 'emergency obstetric care',
                       'labour room', 'maternity', 'high-risk pregnancy', 'blood bank', 'anaesthesia', 'anesthesia',
                       'gynecologyAndObstetrics', 'maternalFetalMedicineOrPerinatology', 'NICU', 'neonatal'):
            self.assertTrue(blocked(phrase), phrase)

    def test_block_leaves_generic_text(self):
        for phrase in ('Laparoscopic surgeries', 'ICU with ventilators', '24x7 emergency', 'basic section of the ward'):
            self.assertFalse(blocked(phrase), phrase)

    def test_feature_names_and_indicators_are_clean(self):
        names = facility_features(ROW)[0]
        self.assertFalse([n for n in names if blocked(n)])
        for key, (pattern, label) in INDICATORS.items():
            self.assertFalse(BLOCK.search(pattern) or BLOCK.search(label) or blocked(key), key)
        for family, pattern in SPECIALTY_FAMILIES:
            self.assertFalse(blocked(family), family)

    def test_no_label_derived_features(self):
        names = facility_features(ROW)[0]
        self.assertFalse([n for n in names if any(w in n for w in ('tier', 'strong', 'moderate', 'claim', 'direct'))])


class FeatureTest(unittest.TestCase):
    def test_values_and_citations(self):
        f, cite = facility_features(ROW)
        self.assertEqual(f['type_hospital'], 1.0)
        self.assertEqual(f['ind_ventilator'], 1.0)
        self.assertEqual(cite['ind_ventilator'], ('equipment', '8-bed ICU with ventilators'))
        self.assertEqual(cite['ind_laparoscopy'], ('procedure', 'Laparoscopic surgeries'))
        self.assertEqual(f['beds_missing'], 0.0)
        self.assertIn('120', feature_label('log_beds', ROW))

    def test_implausible_numbers_are_missing(self):
        f, _ = facility_features({**ROW, 'capacity': '200000', 'yearEstablished': '3020'})
        self.assertEqual(f['beds_missing'], 1.0)
        self.assertEqual(f['age_missing'], 1.0)

    def test_specialty_families(self):
        self.assertEqual(specialty_family('pediatricDentistry'), 'dental')
        self.assertEqual(specialty_family('cataractAndAnteriorSegmentSurgery'), 'eye')
        self.assertEqual(specialty_family('generalSurgery'), 'surgical')
        self.assertEqual(specialty_family('criticalCareMedicine'), 'emergency_critical')
        self.assertEqual(specialty_family('cardiology'), 'medical_specialty')


def fake_index(rows, dup_group, states):
    return SimpleNamespace(rows=rows, dup_group=dup_group, locations=[{'state': s} for s in states])


class GroupAndFoldTest(unittest.TestCase):
    def test_duplicates_and_same_name_branches_share_a_group_and_region(self):
        rows = [{'name': 'Apex Hospital'}, {'name': 'Apex Hospital'}, {'name': 'Other Clinic'}, {'name': 'Third Care'},
                {'name': 'null'}, {'name': 'null'}]
        dup = [0, 1, 2, 2, 4, 5]                  # rows 2 and 3 are engine duplicates; rows 4/5 only share "null"
        index = fake_index(rows, dup, ['Kerala', 'Uttar Pradesh', 'Bihar', 'Bihar', 'Goa', 'Assam'])
        groups = facility_groups(index)
        self.assertEqual(groups[0], groups[1])     # same name, different states
        self.assertEqual(groups[2], groups[3])     # engine duplicates
        self.assertNotEqual(groups[4], groups[5])  # a missing name is not a shared identity
        regions, moved = group_regions(index, groups)
        self.assertEqual(regions[0], regions[1])
        self.assertEqual(moved, 1)
        for g in set(groups):
            self.assertEqual(len({r for r, gg in zip(regions, groups) if gg == g}), 1)


@unittest.skipUnless(HAVE_ML, 'numpy / scikit-learn not installed')
class ModelTest(unittest.TestCase):
    def setUp(self):
        import numpy as np
        rng = np.random.default_rng(1)
        n = 600
        regions = np.array(['North', 'South', 'West'] * (n // 3))
        x_signal = rng.normal(size=n)
        x_noise = rng.normal(size=n)
        present = (rng.random(n) < 0.5).astype(float)
        y = ((x_signal + 0.5 * present + rng.normal(scale=0.5, size=n)) > 1.3).astype(int)
        self.data = {'names': ['signal', 'noise', 'type_hospital'],
                     'X': np.column_stack([x_signal, x_noise, present]).tolist(),
                     'y': y.tolist(), 'regions': regions.tolist(), 'tiers': ['strong' if v else 'none' for v in y]}

    def test_held_out_scores_separate_classes(self):
        from carematch.lead_model import cross_validate, metrics
        oof, models = cross_validate(self.data)
        self.assertEqual(set(models), {'North', 'South', 'West'})
        self.assertGreater(metrics(self.data['y'], oof)['roc_auc'], 0.85)

    def test_each_region_scored_by_a_model_that_never_saw_it(self):
        import numpy as np
        from carematch.lead_model import cross_validate
        data = dict(self.data)
        # Make North's labels impossible to learn from other regions: a model trained on North would score it perfectly.
        y = np.array(data['y'])
        north = np.array(data['regions']) == 'North'
        y[north] = (np.array(data['X'])[north, 1] > 0).astype(int)   # North depends only on "noise"
        data['y'] = y.tolist()
        oof, _ = cross_validate(data)
        from sklearn.metrics import roc_auc_score
        self.assertLess(roc_auc_score(y[north], oof[north]), 0.75)

    def test_metrics_match_sklearn_and_respect_min_positives(self):
        from sklearn.metrics import average_precision_score, roc_auc_score
        from carematch.lead_model import metrics
        y, s = [0, 0, 1, 1, 0, 1], [0.1, 0.4, 0.35, 0.8, 0.2, 0.9]
        m = metrics(y, s, ks=(2,))
        self.assertAlmostEqual(m['roc_auc'], round(roc_auc_score(y, s), 3))
        self.assertAlmostEqual(m['pr_auc'], round(average_precision_score(y, s), 3))
        self.assertEqual(m['precision_at_2'], 1.0)
        self.assertIn('note', metrics(y, s, min_positives=5))

    def test_explanations_cite_only_present_features(self):
        from carematch.lead_model import explain, make_model
        import numpy as np
        model = make_model().fit(self.data['X'], self.data['y'])
        absent = [2.0, 0.0, 0.0]                     # strong signal, type_hospital absent
        reasons, cited = explain(model, absent, self.data['names'], {}, {'signal': ('procedure', 'text')})
        self.assertTrue(all('listed as a hospital' not in r for r in reasons))
        self.assertTrue(np.isfinite(len(reasons)))


if __name__ == '__main__':
    unittest.main()
