import os
import unittest

from carematch import datasource
from carematch.datasource import cell, to_rows

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
HAVE_DATA = all(os.path.exists(os.path.join(DATA, f)) for f in datasource.FILES)

FACILITY_DOUBLES = ('latitude', 'longitude')
PIN_INTS = ('n_offices', 'n_geocoded')
PIN_DOUBLES = ('lat', 'lon', 'lat_min', 'lat_max', 'lon_min', 'lon_max')


def as_spark(row, ints=(), doubles=()):
    """What Spark would hand back for a CSV row: NULL for empty, numbers for numeric columns."""
    out = {}
    for k, v in row.items():
        if v == '':
            out[k] = None
        elif k in ints:
            out[k] = int(v)
        elif k in doubles:
            out[k] = float(v)
        else:
            out[k] = v
    return out


class CellTest(unittest.TestCase):
    def test_conversions(self):
        self.assertEqual(cell(None), '')
        self.assertEqual(cell(float('nan')), '')
        self.assertEqual(cell(19.076), '19.076')
        self.assertEqual(cell(19.0), '19.0')
        self.assertEqual(cell(12), '12')
        self.assertEqual(cell('["dialysis"]'), '["dialysis"]')
        self.assertEqual(cell('null'), 'null')

    def test_to_rows(self):
        rows = to_rows(['a', 'b'], [(1, None), ('x', 2.5)])
        self.assertEqual(rows, [{'a': '1', 'b': ''}, {'a': 'x', 'b': '2.5'}])

    def test_no_source_raises_with_reasons(self):
        with self.assertRaises(RuntimeError) as ctx:
            datasource.load(order=['warehouse'])
        self.assertIn('warehouse', str(ctx.exception))


@unittest.skipUnless(HAVE_DATA, 'data/*.csv not exported')
class ParityTest(unittest.TestCase):
    """Rows read through Spark or a SQL warehouse must equal the CSV rows the engine was calibrated on."""

    @classmethod
    def setUpClass(cls):
        cls.facilities, cls.pincodes, cls.info = datasource.load(order=['local'])

    def test_local_load(self):
        self.assertEqual(self.info['source'], 'local')
        self.assertGreater(len(self.facilities), 10000)
        self.assertGreater(len(self.pincodes), 15000)

    def test_facility_rows_round_trip(self):
        cols = list(self.facilities[0])
        for row in self.facilities:
            typed = as_spark(row, doubles=FACILITY_DOUBLES)
            self.assertEqual(to_rows(cols, [[typed[c] for c in cols]])[0], row)

    def test_pincode_rows_round_trip(self):
        cols = list(self.pincodes[0])
        for row in self.pincodes:
            typed = as_spark(row, ints=PIN_INTS, doubles=PIN_DOUBLES)
            self.assertEqual(to_rows(cols, [[typed[c] for c in cols]])[0], row)


if __name__ == '__main__':
    unittest.main()
