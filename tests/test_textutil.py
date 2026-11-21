import unittest

from carematch.textutil import fragments, haversine_km, source_urls, split_camel, valid_coords


class TextUtilTests(unittest.TestCase):
    def test_fragments_parses_json_array_and_drops_nulls_and_dupes(self):
        self.assertEqual(fragments('["a", null, "", "a", "b"]'), ['a', 'b'])

    def test_fragments_treats_null_strings_as_empty(self):
        for raw in (None, '', '[]', 'null', 'None'):
            self.assertEqual(fragments(raw), [])

    def test_fragments_keeps_plain_text(self):
        self.assertEqual(fragments('Dialysis unit'), ['Dialysis unit'])

    def test_fragments_ignores_object_keys(self):
        self.assertEqual(fragments('{"type": "Point", "coordinates": [1, 2]}'), ['Point'])

    def test_split_camel(self):
        self.assertEqual(split_camel('obstetricsAndGynecology'), 'obstetrics And Gynecology')

    def test_source_urls_filters_nulls_and_non_urls(self):
        self.assertEqual(source_urls('["https://a.in/x", null, "not a url"]'), ['https://a.in/x'])

    def test_valid_coords_india_box(self):
        self.assertEqual(valid_coords(19.07, 72.88), (19.07, 72.88))
        self.assertIsNone(valid_coords(59.9, -38.3))
        self.assertIsNone(valid_coords(None, 72.0))
        self.assertIsNone(valid_coords(True, 72.0))

    def test_haversine_mumbai_pune(self):
        self.assertAlmostEqual(haversine_km((19.076, 72.878), (18.520, 73.857)), 120, delta=5)


if __name__ == '__main__':
    unittest.main()
