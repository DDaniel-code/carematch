"""End-to-end app test (Streamlit AppTest) for the default ranking and the optional preferences.

Slow (loads and warms the full index, ~30 s), so it runs only with CAREMATCH_APP_TEST=1 and the data export present.
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.environ.get('CAREMATCH_APP_TEST') and os.path.exists(os.path.join(ROOT, 'data', 'facilities.csv'))


@unittest.skipUnless(RUN, 'set CAREMATCH_APP_TEST=1 with data/ present')
class AppPreferenceTests(unittest.TestCase):
    def _search(self, service, place, urgency=None, cost=None):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(ROOT, 'app', 'app.py'), default_timeout=300)
        at.run()
        at.selectbox[0].set_value(service)
        at.text_input(key='place').set_value(place)
        if urgency:
            at.radio(key='urgency').set_value(urgency)
        if cost:
            at.radio(key='cost').set_value(cost)
        next(b for b in at.button if 'Find care' in str(b.label)).click()
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def test_default_and_preferences(self):
        at = self._search('Dialysis', 'Patna')
        headings = [m.value for m in at.markdown if m.value.startswith('#### 1.')]
        self.assertTrue(headings)
        self.assertFalse(any(m.value.startswith('**Preference score') for m in at.markdown))
        self.assertTrue(any('passed' in s.value for s in at.success))

        at = self._search('Dialysis', 'Kohima', cost='Prefer free / government-scheme / insured care')
        self.assertTrue(any(m.value.startswith('**Preference score') for m in at.markdown))
        self.assertTrue(any('Cost not documented' in m.value for m in at.markdown))
        self.assertTrue(any('Trade-off' in w.value for w in at.warning))
        self.assertTrue(any('passed' in s.value for s in at.success))


if __name__ == '__main__':
    unittest.main()
