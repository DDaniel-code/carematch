"""CareMatch Databricks App: pick a service, type a place, get up to three facilities with quoted evidence.

UI only. All ranking logic lives in the carematch package (same code the notebooks and tests run).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st  # noqa: E402

from carematch import datasource  # noqa: E402
from carematch.recommend import BANDS_KM, CareIndex, recommend  # noqa: E402
from carematch.services import SERVICES  # noqa: E402

st.set_page_config(page_title='CareMatch', page_icon='🏥', layout='centered')

TIER_TEXT = {'strong': ':green[**Strong evidence**]', 'moderate': ':orange[**Moderate evidence — verify**]',
             'weak': ':gray[**Weak — mentioned, unverified**]'}
FIELD_TEXT = {'procedure': 'procedures', 'equipment': 'equipment', 'capability': 'capabilities',
              'description': 'description', 'specialties': 'specialties', 'operatorTypeId': 'operator type'}
EXAMPLES = 'Patna · Lucknow · 800001 · Darbhanga, Bihar · 25.61, 85.14'


def esc(value):
    """Escape characters Streamlit markdown would interpret ($ starts LaTeX, * and _ emphasis, ...)."""
    out = str(value or '')
    for ch in '\\`*_{}[]<>#|~$':
        out = out.replace(ch, '\\' + ch)
    return out


# ---- data ----------------------------------------------------------------------------------------------------

@st.cache_resource(show_spinner='Loading 10,000 facilities and checking their evidence for 9 services. '
                                'This happens once after the app starts (about a minute); searches are instant after that.')
def get_index():
    """Load and fully warm the index before the first search.

    Warm-up is done here rather than in a background thread: a CPU-bound thread starves Streamlit's own thread
    of the GIL (measured: a first search took 16 s instead of 3 s). The cache is shared by every visitor,
    so only the first visit after a deploy waits.
    """
    facilities, pincodes, info = datasource.load()
    started = time.perf_counter()
    index = CareIndex(facilities, pincodes)
    for service in SERVICES:
        index.assessments(service)
    info['index_seconds'] = round(time.perf_counter() - started, 1)
    return index, info


# ---- rendering -----------------------------------------------------------------------------------------------

def _set_place(value):
    st.session_state.place = value


def render_card(c, heading):
    with st.container(border=True):
        st.markdown(f'#### {heading}')
        dist = (f"**{c['distance_km']} km** away" if c['distance_km'] is not None else '**distance unknown**')
        basis = '' if c.get('distance_basis') in (None, 'facility coordinates') else f" (from {esc(c['distance_basis'])})"
        meta = ' · '.join(esc(x) for x in (c.get('type'), c.get('operator'),
                                           f"{c['beds']} beds" if c.get('beds') else None,
                                           f"found within {c['found_within_km']} km" if c.get('found_within_km') else None)
                          if x)
        st.markdown(f"{TIER_TEXT.get(c['tier'], esc(c['tier']))}  \n{dist}{basis}" + (f" · {meta}" if meta else ''))
        place = ', '.join(esc(x) for x in (c.get('address') or c.get('city'), f"PIN {c['pin']}" if c.get('pin') else None) if x)
        if place:
            st.caption(place)

        st.markdown('**What the records say**')
        for e in c['evidence']:
            st.markdown(f"> “{esc(e['quote'])}”  \n> — *{FIELD_TEXT.get(e['field'], esc(e['field']))}* field")
        if c.get('tier_reasons'):
            st.markdown('**Why this tier:** ' + esc('; '.join(c['tier_reasons'])))
        if c.get('why_ranked'):
            st.markdown('**Why this order:** ' + esc(c['why_ranked']))

        pref = c.get('preference')
        if pref:
            st.markdown(f"**Preference score {pref['score']:.2f}** <span style='color:gray'>(a ranking weight from stated "
                        f"assumptions, not a chance of treatment)</span>", unsafe_allow_html=True)
            for comp in pref['components']:
                value = 'n/a' if comp['value'] is None else f"{comp['value']:.2f} × weight {comp['weight']:.2f}"
                line = f"- *{esc(comp['name'])}* ({value}): {esc(comp['reason'])}"
                if comp.get('quote'):
                    line += f"  \n  “{esc(comp['quote'])}” — *{FIELD_TEXT.get(comp['field'], esc(comp['field']))}*"
                for s in comp.get('signals', []):
                    line += f"  \n  {esc(s['signal'])}: “{esc(s['quote'])}” — *{FIELD_TEXT.get(s['field'], esc(s['field']))}*"
                st.markdown(line)
        if c.get('cost'):
            cost = c['cost']
            st.caption('💰 Cost: ' + ({'covered': 'free / government scheme documented', 'insured': 'cashless / insurance documented',
                                         'unknown': 'not documented in the record (ask when calling)'}[cost['category']]))

        if c.get('uncertainties'):
            st.markdown('**Not certain**  \n' + '  \n'.join(f'⚠️ {esc(u)}' for u in c['uncertainties']))
        if c.get('note'):
            st.info(c['note'])

        phone = c.get('phone')
        if phone:
            st.markdown(f"📞 **Call before you go:** [{esc(phone)}](tel:{phone.replace(' ', '')})")
        else:
            st.markdown('📞 No phone number in the records.')
        st.markdown('**Ask when you call**  \n' + '  \n'.join(f'• {esc(q)}' for q in c.get('ask_when_calling', [])))

        with st.expander('Sources and details'):
            for u in c.get('source_urls', []):
                st.markdown(f'- {esc(u)}')
            if c.get('website'):
                st.markdown(f"- Website: {esc(c['website'])}")
            st.caption(f"Facility id {esc(c['facility_id'])} · {c.get('all_evidence_count', 0)} evidence items · "
                       f"location confidence: {esc(c.get('location_confidence'))}"
                       + (f" · merged listings: {esc(', '.join(c['merged_ids']))}" if c.get('merged_ids') else ''))


def render_result(r):
    o = r['origin']
    st.markdown(f"**{esc(r['service_label'])}** near **{esc(o['label'])}** "
                f"<span style='color:gray'>(location precision about {o['precision_km']} km)</span>",
                unsafe_allow_html=True)
    if r.get('service_scope'):
        st.caption(f"**What the records can show:** {esc(r['service_scope'])}")
    for note in o.get('notes', []):
        st.caption(note)
    if o.get('alternatives'):
        cols = st.columns(len(o['alternatives']))
        for col, alt in zip(cols, o['alternatives']):
            # A callback may set the text box's state; assigning it after the widget is drawn would raise.
            col.button(f'Use {alt}', key=f'alt-{alt}', on_click=_set_place, args=(alt,))

    review = r.get('review')
    if review:
        ok = sum(1 for chk in review.get('checks', []) if chk.get('passed'))
        total = len(review.get('checks', []))
        (st.success if review.get('passed') else st.error)(f'Quality checks: {ok}/{total} passed')

    if r.get('action_advice'):
        st.info(f"**Next step:** {esc(r['action_advice'])}", icon='📞')
    if (r.get('preferences') or {}).get('applied'):
        st.caption('Ordered by your preferences. The evidence gate and search radius are the same as the default ranking.')
        if r.get('tradeoff_note'):
            st.warning(f"**Trade-off:** {esc(r['tradeoff_note'])}", icon='⚖️')
    if r['results']:
        st.markdown(f"Showing facilities with credible evidence within **{r['band_km']} km**.")
        for c in r['results']:
            render_card(c, f"{c['rank']}. {esc(c['name'])}")
    if r.get('cost_unknown_options'):
        st.markdown('---\n**Cost not documented in the record** (may still be free or covered; ask when calling)')
        for c in r['cost_unknown_options']:
            render_card(c, esc(c['name']))
    else:
        st.warning(f'No facility with credible evidence within {BANDS_KM[-1]} km. '
                   'This is an honest answer, not an error: the records do not support a recommendation here.')
    if r.get('farther_stronger'):
        st.markdown('---\n**Farther away, but stronger evidence**')
        render_card(r['farther_stronger'], esc(r['farther_stronger']['name']))
    if r.get('nearest_beyond'):
        st.markdown('---\n**Nearest facility with credible evidence**')
        render_card(r['nearest_beyond'], esc(r['nearest_beyond']['name']))
    if r.get('weak_nearby'):
        st.markdown('---\n**Mentioned nearby, but the evidence is weak (not recommended)**')
        for c in r['weak_nearby']:
            render_card(c, esc(c['name']))

    with st.expander('How we decided'):
        st.markdown(esc(r['method']))
        if r.get('preference_model'):
            m = r['preference_model']
            st.markdown('**Preference model** (re-orders the same credible options)  \n'
                        + '  \n'.join(f"- {esc(k)}: {esc(v)}" for k, v in m.items() if k not in ('urgency', 'cost')))
        rows = [{'within': f'{km} km', 'strong': v['strong'], 'moderate': v['moderate'], 'weak': v['weak']}
                for km, v in r['considered']['by_band'].items()]
        st.dataframe(rows, hide_index=True)
        skipped = r['considered'].get('recommendable_without_location')
        if skipped:
            st.caption(f'{skipped} facilities with credible evidence were skipped because their location is unknown.')
        if r.get('runner_ups'):
            st.markdown('**Why not these nearby facilities?**')
            for c in r['runner_ups']:
                dist = f"{c['distance_km']} km" if c.get('distance_km') is not None else 'distance unknown'
                st.markdown(f"- **{esc(c['name'])}** ({dist}): {esc(c.get('why_not', ''))}")
        if review:
            for chk in review.get('checks', []):
                st.markdown(f"{'✅' if chk.get('passed') else '❌'} {esc(chk.get('name'))}"
                            + (f" — {esc(chk.get('detail'))}" if chk.get('detail') else ''))
    st.caption(r['disclaimer'])


# ---- page ----------------------------------------------------------------------------------------------------

st.title('CareMatch')
st.markdown('Find a facility for a specific kind of care in India, with the evidence behind every suggestion.')

try:
    index, info = get_index()
except Exception as exc:  # a data failure must never look like "no hospitals found"
    st.error(f'Could not load the facility data, so no search is possible right now.\n\n{exc}')
    st.stop()

labels = {spec['label']: key for key, spec in SERVICES.items()}
with st.form('search'):
    service_label = st.selectbox('Service needed', list(labels))
    place = st.text_input('Where is the patient?', key='place',
                          placeholder='City, district, 6-digit PIN code, or "lat, lon"')
    st.caption(f'Examples: {EXAMPLES}')
    with st.expander('Preferences (optional)'):
        urgency_options = {'Default: evidence first, then distance': 'default',
                           'Time-critical: every minute on the road counts': 'time_critical',
                           'Can travel further for better-prepared care': 'can_travel'}
        cost_options = {'Cost does not change the order': 'any',
                        'Prefer free / government-scheme / insured care': 'low_cost'}
        urgency_label = st.radio('How urgent is it?', list(urgency_options), key='urgency')
        cost_label = st.radio('Cost', list(cost_options), key='cost')
    submitted = st.form_submit_button('Find care', type='primary')

if submitted or st.session_state.get('place'):
    if not (st.session_state.get('place') or '').strip():
        st.info('Type a place to search from.')
    else:
        prefs = {'urgency': urgency_options[urgency_label], 'cost': cost_options[cost_label]}
        with st.spinner('Checking the evidence…'):
            result = recommend(index, labels[service_label], st.session_state.place, preferences=prefs)
        if 'error' in result:
            st.error(result['error'])
        else:
            render_result(result)

with st.sidebar:
    st.markdown('**Data**')
    st.caption(f"Source: {info['source']} · {info['facility_rows']:,} facilities · {info['pincode_rows']:,} PIN rows · "
               f"loaded in {info['load_seconds']} s, indexed in {info['index_seconds']} s")
    for failure in info.get('failed_sources', []):
        st.caption(f'Fallback used; failed: {failure}')
    st.markdown('**About**')
    st.caption('Recommendations come from public web listings compiled by the Virtue Foundation. '
               'A listing saying a facility offers a service is evidence, not proof. Always call first.')
