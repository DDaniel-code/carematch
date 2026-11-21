import json
import unittest

from carematch.geo import Gazetteer, canonical_state, city_key, facility_location
from carematch.recommend import CareIndex, recommend

# Synthetic geography around two real-ish places (coordinates approximate, data invented).
PATNA, MUZ, MUMBAI = (25.60, 85.14), (26.12, 85.39), (19.07, 72.88)


def pin_row(pin, district, state, lat, lon, spread=0.05):
    return {'pincode': pin, 'district': district, 'statename': state, 'n_offices': '5', 'n_geocoded': '5',
            'lat': str(lat), 'lon': str(lon), 'lat_min': str(lat - spread), 'lat_max': str(lat + spread),
            'lon_min': str(lon - spread), 'lon_max': str(lon + spread)}


PINS = [pin_row(f'8000{i:02d}', 'PATNA', 'BIHAR', PATNA[0] + i * 0.01, PATNA[1]) for i in range(1, 8)]
PINS += [pin_row(f'8420{i:02d}', 'MUZAFFARPUR', 'BIHAR', MUZ[0] + i * 0.01, MUZ[1]) for i in range(1, 8)]
PINS += [pin_row(f'4000{i:02d}', 'MUMBAI', 'MAHARASHTRA', MUMBAI[0] + i * 0.01, MUMBAI[1]) for i in range(1, 8)]
# A Bihar PIN wrongly geocoded to Mumbai (same-name collision in the real data looks like this)
PINS.append(pin_row('800099', 'PATNA', 'BIHAR', MUMBAI[0], MUMBAI[1]))


def fac(uid, name, city, state, pin, lat, lon, ftype='hospital', **claims):
    row = {'unique_id': uid, 'name': name, 'address_city': city, 'address_stateOrRegion': state,
           'address_zipOrPostcode': pin, 'latitude': '' if lat is None else str(lat),
           'longitude': '' if lon is None else str(lon), 'facilityTypeId': ftype, 'capacity': '100',
           'officialPhone': '+910000000000', 'phone_numbers': '[]', 'source_urls': '[]'}
    row.update({k: json.dumps(v) for k, v in claims.items()})
    return row


STRONG_DIALYSIS = {'procedure': ['Provides hemodialysis'], 'equipment': ['10 dialysis machines']}
FACILITIES = [
    fac('p1', 'Patna Kidney Care', 'Patna', 'Bihar', '800001', PATNA[0] + 0.01, PATNA[1] + 0.01, **STRONG_DIALYSIS),
    fac('p2', 'Patna General', 'Patna', 'Bihar', '800002', PATNA[0] + 0.02, PATNA[1], procedure=['Dialysis']),
    fac('p3', 'Patna Clinic', 'Patna', 'Bihar', '800003', PATNA[0], PATNA[1] + 0.02, specialties=['nephrology']),
    fac('p4', 'Patna Kidney Care', 'Patna', 'Bihar', '800001', PATNA[0] + 0.011, PATNA[1] + 0.01, **STRONG_DIALYSIS),
    fac('p5', 'Patna Ortho', 'Patna', 'Bihar', '800004', PATNA[0] + 0.03, PATNA[1], procedure=['Knee replacement']),
    fac('m1', 'Muz Renal', 'Muzaffarpur', 'Bihar', '842001', MUZ[0], MUZ[1], **STRONG_DIALYSIS),
    # coordinates point to Mumbai but PIN and city say Patna -> coordinates are the error
    fac('x1', 'Misplaced Hospital', 'Patna', 'Bihar', '800005', MUMBAI[0], MUMBAI[1], procedure=['Knee replacement']),
    fac('n1', 'No Coords Hospital', 'Patna', 'Bihar', '800006', None, None, procedure=['Knee replacement']),
] + [fac(f'mb{i}', f'Mumbai H{i}', 'Mumbai', 'Maharashtra', '400001', MUMBAI[0] + i * 0.01, MUMBAI[1],
         procedure=['General surgery']) for i in range(5)]


class GeoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gaz = Gazetteer(PINS, FACILITIES)

    def test_state_and_city_normalization(self):
        self.assertEqual(canonical_state('Tamilnadu'), 'Tamil Nadu')
        self.assertEqual(canonical_state('Orissa'), 'Odisha')
        self.assertIsNone(canonical_state('Thane'))
        self.assertEqual(city_key('Bangalore'), city_key('Bengaluru'))

    def test_resolve_pin_city_coords(self):
        self.assertEqual(self.gaz.resolve('800001')['kind'], 'pin')
        self.assertEqual(self.gaz.resolve('Patna')['kind'], 'city')
        self.assertEqual(self.gaz.resolve('25.6, 85.1')['kind'], 'coordinates')
        self.assertIn('error', self.gaz.resolve('Atlantis'))
        self.assertIn('error', self.gaz.resolve('59.9, -38.3'))

    def test_misgeocoded_pin_centre_dropped(self):
        self.assertFalse(self.gaz.pin_info('800099')['reliable'])

    def test_unknown_pin_falls_back_to_area(self):
        loc = self.gaz.resolve('800050')
        self.assertEqual(loc['kind'], 'pin_area')
        self.assertTrue(loc['notes'])

    def test_wrong_coordinates_replaced_by_pin(self):
        loc = facility_location(FACILITIES[6], self.gaz)
        self.assertIn('coords_wrong_used_pin', loc['flags'])
        self.assertEqual(loc['confidence'], 'approximate')

    def test_missing_coordinates_use_pin(self):
        loc = facility_location(FACILITIES[7], self.gaz)
        self.assertIn('position_from_pin', loc['flags'])
        self.assertIsNotNone(loc['position'])


class RecommendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = CareIndex(FACILITIES, PINS)

    def test_strong_first_and_weak_excluded(self):
        r = recommend(self.idx, 'dialysis', 'Patna')
        names = [c['name'] for c in r['results']]
        self.assertEqual(r['band_km'], 25)
        self.assertEqual(names[0], 'Patna Kidney Care')
        self.assertIn('Patna General', names)
        self.assertNotIn('Patna Clinic', names)          # specialty-only = weak
        self.assertNotIn('Muz Renal', names)             # ~60 km away, outside the 25 km band

    def test_duplicates_merged(self):
        r = recommend(self.idx, 'dialysis', 'Patna')
        self.assertEqual(sum(c['name'] == 'Patna Kidney Care' for c in r['results']), 1)
        self.assertIn('possible_duplicate_listing', r['results'][0]['flags'])

    def test_every_result_cites_evidence(self):
        for c in recommend(self.idx, 'dialysis', 'Patna')['results']:
            self.assertTrue(c['evidence'])
            for e in c['evidence']:
                self.assertTrue(e['quote'] and e['field'])
            self.assertTrue(c['ask_when_calling'])

    def test_farther_stronger_option(self):
        r = recommend(self.idx, 'dialysis', '842001')   # Muzaffarpur: strong nearby
        self.assertEqual(r['results'][0]['name'], 'Muz Renal')

    def test_no_answer_is_honest(self):
        r = recommend(self.idx, 'dialysis', 'Mumbai')
        self.assertEqual(r['results'], [])
        self.assertIsNotNone(r['nearest_beyond'])      # Patna/Muzaffarpur, > 300 km
        self.assertGreater(r['nearest_beyond']['distance_km'], 300)

    def test_approximate_location_widens_and_keeps_nearer_first(self):
        r = recommend(self.idx, 'dialysis', '800050')          # unknown PIN -> PIN area, +-25 km
        self.assertEqual(r['origin']['kind'], 'pin_area')
        self.assertGreaterEqual(r['band_km'], 75)
        self.assertTrue(any('search starts at' in n for n in r['origin']['notes']))
        self.assertTrue(r['review']['passed'])
        self.assertIn('action_advice', r)

    def test_bad_inputs(self):
        self.assertIn('error', recommend(self.idx, 'acupuncture', 'Patna'))
        self.assertIn('error', recommend(self.idx, 'dialysis', ''))

    def test_deterministic(self):
        a = recommend(self.idx, 'dialysis', 'Patna')
        b = recommend(self.idx, 'dialysis', 'Patna')
        self.assertEqual([c['facility_id'] for c in a['results']], [c['facility_id'] for c in b['results']])


if __name__ == '__main__':
    unittest.main()
