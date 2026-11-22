"""Outcome-based tests of the Find Care app (Streamlit AppTest on the real exported data).

Each test checks what a visitor would see, not how the page is built: a consistent status line, numbered cards,
directions links that carry only the destination, prices never invented, public never called free, honest
"cannot be ranked" answers, the strategy comparison, and a usable page when the map library is missing.

Slow (the first search loads and warms the full index, ~30-60 s; later searches reuse it). Runs when data/ is present;
set CAREMATCH_SKIP_APP_TEST=1 to skip.
"""
import os
import re
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'app', 'Find_care.py')
RUN = os.path.exists(os.path.join(ROOT, 'data', 'facilities.csv')) and not os.environ.get('CAREMATCH_SKIP_APP_TEST')
try:
    import streamlit  # noqa: F401
except ImportError:
    RUN = False


def text(at):
    """Every markdown, caption and alert as plain text (HTML tags removed)."""
    parts = [m.value for m in at.markdown if '<style>' not in m.value] + [c.value for c in at.caption]
    parts += [x.value for x in list(at.info) + list(at.warning) + list(at.error) + list(at.success)]
    plain = (re.sub(r'<[^>]+>', ' ', p).replace('&#x27;', "'").replace('&amp;', '&') for p in parts)
    return [re.sub(r'[ \t]+', ' ', p.replace('**', '')) for p in plain]


def status(at):
    return next((re.sub(r'<[^>]+>', ' ', m.value) for m in at.markdown if 'cm-status' in m.value and '<style>' not in m.value), '')


def card_titles(at):
    return [re.sub(r'<[^>]+>', ' ', m.value).split('Strong')[0].split('Moderate')[0].strip()
            for m in at.markdown if 'cm-title' in m.value and '<style>' not in m.value]


def links(at):
    out = []
    for b in at.get('link_button'):
        proto = b.proto
        out.append((proto.label, proto.url))
    return out


@unittest.skipUnless(RUN, 'needs streamlit and data/facilities.csv (set CAREMATCH_SKIP_APP_TEST=1 to skip)')
class FindCareOutcomes(unittest.TestCase):
    def setUp(self):
        self._saved = {k: sys.modules.get(k) for k in ('carematch.strategy_compare', 'pydeck')}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def search(self, service, place, sort=None, cost=None, extra=None):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(APP, default_timeout=600)
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        at.selectbox[0].set_value(service)
        at.text_input(key='place').set_value(place)
        if cost:
            at.radio(key='cost').set_value(cost)
        next(b for b in at.button if 'Find care' in str(b.label)).click()
        at.run()
        if sort:
            at.radio(key='sort').set_value(sort).run()
        if extra is not None:
            at.slider(key='max_extra_km').set_value(extra).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    # -- default order --------------------------------------------------------------------------------------------

    def test_default_answer_is_numbered_cited_and_consistent(self):
        at = self.search('Dialysis', 'Patna')
        s = status(at)
        self.assertRegex(s, r'3 options with credible evidence within 25 km')
        self.assertNotIn('No facility', s)
        titles = card_titles(at)
        self.assertEqual([t[:1] for t in titles[:3]], ['1', '2', '3'])
        self.assertTrue(any('“' in t and 'field' in t for t in text(at)), 'a verbatim quote with its column')
        self.assertTrue(any('Next step' in t for t in text(at)))

    def test_directions_carry_only_the_destination(self):
        at = self.search('Dialysis', 'Patna')
        maps = [(label, url) for label, url in links(at) if 'google.com/maps' in url]
        self.assertTrue(maps)
        labels = {label for label, _ in maps}
        self.assertTrue({'Directions', 'Driving · try to avoid tolls', 'Walking'} <= labels, labels)
        for label, url in maps:
            q = parse_qs(urlsplit(url).query)
            self.assertNotIn('origin', q)
            self.assertEqual(q['api'], ['1'])
            self.assertRegex(q['destination'][0], r'^-?\d+\.\d{5},-?\d+\.\d{5}$')
            mode = q['travelmode'][0]
            if label == 'Driving · try to avoid tolls':
                self.assertEqual((mode, q.get('avoid')), ('driving', ['tolls']))
            elif label == 'Directions':
                self.assertEqual(mode, 'driving')
                self.assertNotIn('avoid', q)
            else:
                self.assertEqual(mode, 'walking')
                self.assertNotIn('avoid', q)

    def test_no_answer_is_said_once_without_contradiction(self):
        at = self.search('Burn care', 'Port Blair')
        s = status(at)
        self.assertIn('No facility with credible evidence within 300 km', s)
        self.assertNotRegex(' '.join(text(at)), r'\d+ options? with credible evidence within')

    # -- costs and prices -----------------------------------------------------------------------------------------

    def test_public_operator_is_never_called_free(self):
        at = self.search('Dialysis', 'Patna', cost='Prefer care documented as free, government-scheme or insured')
        for t in text(at):
            if 'Public operator' in t:
                self.assertNotRegex(t.split('Public operator', 1)[1][:120].lower(), r'\bfree\b')

    def test_price_order_discloses_unknown_and_never_claims_cheapest_without_evidence(self):
        at = self.search('Dialysis', 'Mumbai', sort='Compare listed prices')
        joined = ' '.join(text(at))
        self.assertIn('Price: not documented', joined)
        self.assertIn('an unknown price is not assumed high or low', joined)
        self.assertNotIn('cheapest', status(at).lower())
        self.assertTrue(any('Extra distance' in str(s.label) for s in at.slider))

    def test_documented_price_is_shown_as_quoted(self):
        at = self.search('MRI scan', '126102', sort='Compare listed prices', extra=50)
        joined = ' '.join(text(at))
        self.assertIn('₹3,000', joined)
        self.assertIn('unit not stated', joined)

    def test_emergency_price_order_carries_a_safety_note(self):
        at = self.search('C-section (caesarean delivery)', 'Lucknow', sort='Compare listed prices')
        self.assertTrue(any('emergency' in w.value.lower() for w in at.warning))

    # -- strategy comparison ----------------------------------------------------------------------------------------

    def test_comparison_shows_actual_changes_and_evidence(self):
        at = self.search('Dialysis', 'Delhi')
        joined = ' '.join(text(at))
        self.assertIn('1.6 km closer', joined)
        self.assertIn('Moolchand Hospital', joined)
        self.assertIn('Dashmesh Hospital', joined)
        self.assertIn('Price comparison falls back to distance', joined)
        self.assertTrue(any('side by side' in e.label for e in at.expander))
        self.assertIn('Differs from Best evidence: weaker evidence (Moderate instead of Strong), 1.6 km closer', joined)
        at.radio(key='sort').set_value('Nearest').run()
        self.assertIn('Moolchand', card_titles(at)[0])
        at.radio(key='sort').set_value('Compare listed prices').run()
        self.assertIn('Why this is ordered by distance:', ' '.join(text(at)), 'the price fallback gives its reason')
        self.assertIn('prices could not be ranked', status(at))

    def test_description_does_not_override_the_users_travel_preference(self):
        at = self.search('Dialysis', 'Delhi')
        original = at.radio(key='urgency').value
        at.text_input(key='need_text').set_value('kidney failure patient needs dialysis')
        next(b for b in at.button if b.label == 'Suggest a service').click().run()
        self.assertEqual(at.radio(key='urgency').value, original)
        self.assertTrue(any('Suggested service' in m.value for m in at.markdown))

    def test_comparison_with_no_options_is_plain(self):
        at = self.search('Burn care', 'Port Blair')
        self.assertIn('None of these orders returned', ' '.join(text(at)))
        self.assertFalse(any('side by side' in e.label for e in at.expander))

    def test_a_misspelled_place_offers_the_place_it_probably_meant(self):
        at = self.search('Dialysis', 'Banglore')
        self.assertTrue(any('Could not find' in e.value for e in at.error))
        suggestion = next(b for b in at.button if b.label == 'Bengaluru, Karnataka')
        suggestion.click().run()
        self.assertFalse(at.error)
        self.assertRegex(status(at), r'options? with credible evidence within')

    # -- resilience -----------------------------------------------------------------------------------------------

    def test_results_survive_a_missing_map_library(self):
        sys.modules['pydeck'] = None          # import pydeck now raises ImportError
        at = self.search('Dialysis', 'Patna')
        joined = ' '.join(text(at))
        self.assertIn('Map unavailable', joined)
        self.assertTrue(re.search(r'(^|\s)1 · .+? · [\d.]+ km straight-line', joined), 'numbered pins listed as text')
        self.assertGreaterEqual(len(card_titles(at)), 3)


if __name__ == '__main__':
    unittest.main()
