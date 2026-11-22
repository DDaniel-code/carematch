"""CareMatch Databricks App: find care for one service near one place, with the evidence behind every suggestion.

UI only. Ranking, evidence, prices and quality checks live in the carematch package (the same code the notebook and
tests run). This file lays out the search, the numbered list, the matching map pins and the disclosures.
"""
import html
import inspect
import math
import os
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st  # noqa: E402

from carematch import datasource  # noqa: E402
from carematch.recommend import BANDS_KM, CareIndex, recommend  # noqa: E402
from carematch.services import SERVICES  # noqa: E402

st.set_page_config(page_title='CareMatch · Find care', page_icon='🏥', layout='wide')

EXAMPLES = ['Patna', 'Lucknow', '800001', 'Darbhanga, Bihar', '25.61, 85.14']
FIELD_TEXT = {'procedure': 'procedures', 'equipment': 'equipment', 'capability': 'capabilities',
              'description': 'description', 'specialties': 'specialties', 'operatorTypeId': 'operator type'}
TIER_CHIP = {'strong': ('strong', 'Strong evidence'), 'moderate': ('moderate', 'Moderate evidence · verify'),
             'weak': ('weak', 'Weak · not recommended')}
# Services where minutes matter: price sorting is shown with a safety note.
TIME_CRITICAL = {'c_section', 'trauma', 'emergency', 'nicu', 'burn'}
SORTS = {'Best evidence': 'default', 'Nearest': 'nearest', 'Lowest listed price': 'price'}
_PARAMS = set(inspect.signature(recommend).parameters)
SUPPORTS = {'default': True, 'nearest': 'sort_mode' in _PARAMS, 'price': {'sort_mode', 'max_extra_km'} <= _PARAMS}
PRIMARY_RGB, EXTRA_RGB = [26, 95, 122], [95, 107, 118]

CSS = """
<style>
.cm-status{font-size:.95rem;color:#323f4b;margin:.1rem 0 .4rem}
.cm-title{display:flex;align-items:center;gap:.55rem;font-size:1.08rem;font-weight:650;margin:.1rem 0 .3rem;line-height:1.3}
.cm-pin{display:inline-flex;align-items:center;justify-content:center;min-width:1.65rem;height:1.65rem;border-radius:50%;
        background:#1a5f7a;color:#fff;font-weight:700;font-size:.85rem;flex:none}
.cm-pin.extra{background:#5f6b76}
.cm-meta{color:#52606d;font-size:.88rem;margin:.1rem 0}
.cm-chip{display:inline-block;border:1px solid #cbd2d9;border-radius:999px;padding:.05rem .55rem;font-size:.8rem;
         margin:0 .3rem .2rem 0;color:#323f4b;background:#f5f7fa;white-space:nowrap}
.cm-chip.strong{border-color:#2f855a;color:#22543d;background:#f0fff4}
.cm-chip.moderate{border-color:#b7791f;color:#744210;background:#fffaf0}
.cm-chip.weak{border-color:#9aa5b1;color:#3e4c59}
.cm-quote{border-left:3px solid #cbd2d9;padding:.1rem 0 .1rem .6rem;color:#323f4b;margin:.35rem 0;font-size:.92rem}
.cm-quote small{color:#616e7c}
.cm-price{font-size:.9rem;margin:.25rem 0;color:#323f4b}
.cm-warn{font-size:.86rem;color:#7b341e;margin:.15rem 0}
</style>
"""


def esc(value):
    """Escape for Streamlit markdown ($ starts LaTeX, * and _ emphasis, ...)."""
    out = str(value if value is not None else '')
    for ch in '\\`*_{}[]<>#|~$':
        out = out.replace(ch, '\\' + ch)
    return out


def h(value):
    return html.escape(str(value if value is not None else ''))


# ---- data ----------------------------------------------------------------------------------------------------

@st.cache_resource(show_spinner='Loading 10,000 facilities and checking their evidence for 9 services. '
                                'This happens once after the app starts (about a minute); searches are instant after that.')
def get_index():
    """Load and fully warm the index before the first search (a background warm-up thread starves Streamlit of the
    GIL). The cache is shared by every visitor, so only the first visit after a deploy waits."""
    facilities, pincodes, info = datasource.load()
    started = time.perf_counter()
    index = CareIndex(facilities, pincodes)
    for service in SERVICES:
        index.assessments(service)
    info['index_seconds'] = round(time.perf_counter() - started, 1)
    return index, info


def located(index, card):
    """(lat, lon, reliable) for a card. Reliable = the record's own coordinates, agreeing with its PIN and city."""
    if card.get('lat') is not None and card.get('lon') is not None:
        pos = (card['lat'], card['lon'])
    else:
        rows = index.by_id.get(str(card.get('facility_id')), [])
        pos = index.locations[rows[0]]['position'] if rows else None
    if not pos:
        return None
    reliable = (card.get('location_confidence') in ('high', 'medium')
                and (card.get('distance_basis') or 'facility coordinates') == 'facility coordinates'
                and 'location_conflict' not in (card.get('flags') or []))
    return pos[0], pos[1], reliable


def directions_url(lat, lon, mode):
    """Google Maps universal directions URL. Destination only: no origin and nothing about the patient is sent;
    the phone's own location is used as the starting point."""
    params = {'api': '1', 'destination': f'{lat:.5f},{lon:.5f}', 'travelmode': mode}
    if mode == 'driving':
        params['avoid'] = 'tolls'
    return 'https://www.google.com/maps/dir/?' + urlencode(params)


# ---- prices and cost (disclosure only; the engine decides order) --------------------------------------------------

UNIT_TEXT = {'per_session': 'per session', 'per_scan': 'per scan', 'per_day': 'per day', 'per_procedure': 'per procedure',
             'per_month': 'per month', 'package': 'package', 'unspecified': 'unit not stated'}


def price_figure(p):
    """The documented amount as written: exact, range, upper or lower bound, or free. Never filled in."""
    lo, hi = p.get('amount_min_inr'), p.get('amount_max_inr')
    bound = p.get('bound')
    if bound == 'free':
        return 'listed as free'
    if bound == 'range' and lo is not None and hi is not None:
        return f'₹{lo:,.0f}–{hi:,.0f}'
    if bound == 'upper_bound' and hi is not None:
        return f'up to ₹{hi:,.0f}'
    if bound == 'lower_bound' and lo is not None:
        return f'from ₹{lo:,.0f}'
    if lo is not None:
        return f'₹{lo:,.0f}'
    return 'an amount is quoted'


def price_html(card, sort_mode):
    """The documented service price, its unit and conditions, and any amounts that are not prices.
    Unknown prices are said to be unknown, never assumed high or low; a public operator is never called free."""
    p = card.get('price_info')
    out = ''
    if not p:
        if sort_mode == 'price':      # in other orders an absent price adds noise; it is disclosed where price matters
            out = '<div class="cm-price">Price: <b>not documented</b> for this service. Ask when you call.</div>'
    else:
        unit = p.get('unit') or 'unspecified'
        notes = []
        if p.get('bound') == 'free':
            notes.append('a claim of free care: shown, but not ranked as a price; check who qualifies')
        elif unit == 'unspecified':
            notes.append('unit not stated, so not compared with other quotes')
        if p.get('conditions'):
            notes.append('conditions: ' + ', '.join(p['conditions']))
        if p.get('bound') in ('upper_bound', 'lower_bound'):
            notes.append('a bound, not an exact charge')
        if card.get('not_comparable_because'):
            notes.append('not compared: ' + card['not_comparable_because'])
        if p.get('other_price_quotes'):
            notes.append(f"{p['other_price_quotes']} other price quote(s) in the record")
        out = (f'<div class="cm-price">Documented price: <b>{h(price_figure(p))}</b>'
               + (f' {h(UNIT_TEXT.get(unit, unit))}' if unit != 'unspecified' else '')
               + (f'<div class="cm-warn">{h("; ".join(notes))}</div>' if notes else '') + '</div>')
        if p.get('quote'):
            out += (f'<div class="cm-quote">“{h(p["quote"])}”<br><small>— {h(FIELD_TEXT.get(p.get("field"), p.get("field") or "record"))}'
                    ' field · a web quote; confirm the current charge by phone</small></div>')
    for ctx in card.get('price_context') or []:
        amounts = ', '.join(f'₹{a:,.0f}' for a in ctx.get('amounts_inr', [])[:3])
        kind = {'insurer_coverage': 'an insurance or scheme limit', 'capital_or_equipment': 'a building or equipment cost'}.get(
            ctx.get('kind'), 'another amount')
        out += f'<div class="cm-warn">Also mentions {h(amounts)}: {h(kind)}, not a patient price.</div>'
    return out


def cost_text(cost):
    """Plain wording for the documented payment signal. A public operator is not described as free."""
    if not cost:
        return None
    if cost.get('field') == 'operatorTypeId':
        return 'Public operator. Charges are not documented; ask about fees and government schemes.'
    if cost.get('category') == 'covered':
        return 'The record mentions free care or a government scheme (see quote). Eligibility and charges must be confirmed.'
    if cost.get('category') == 'insured':
        return 'The record mentions cashless or insurance payment. Check whether your scheme or insurer is accepted.'
    return 'Cost is not documented in the record. Ask when you call.'


# ---- rendering -----------------------------------------------------------------------------------------------

def _set_place(value):
    st.session_state.place = value


def render_card(index, c, label, sort_mode, extra=False, nested=False):
    """One result. nested=True (inside an expander) drops the card's own details expander, which Streamlit cannot nest."""
    with st.container(border=True):
        kind, chip = TIER_CHIP.get(c.get('tier'), ('weak', str(c.get('tier'))))
        pin = f'<span class="cm-pin{" extra" if extra else ""}" aria-label="Map pin {h(label)}">{h(label)}</span>' if label else ''
        dist = f"{c['distance_km']} km straight-line" if c.get('distance_km') is not None else 'distance unknown'
        meta = ' · '.join(h(x) for x in (dist, c.get('type'), c.get('operator'),
                                         f"{c['beds']} beds" if c.get('beds') else None) if x)
        place = ', '.join(x for x in (c.get('address') or c.get('city'), f"PIN {c['pin']}" if c.get('pin') else None) if x)
        st.markdown(f'<h3 class="cm-title">{pin}<span>{h(c.get("name"))}</span></h3>'
                    f'<div><span class="cm-chip {kind}">{h(chip)}</span>'
                    + (f'<span class="cm-chip">found within {h(c["found_within_km"])} km</span>' if c.get('found_within_km') else '')
                    + f'</div><div class="cm-meta">{meta}</div>'
                    + (f'<div class="cm-meta">{h(place)}</div>' if place else '')
                    + price_html(c, sort_mode), unsafe_allow_html=True)

        if c.get('evidence'):
            e = c['evidence'][0]
            st.markdown(f'<div class="cm-quote">“{h(e["quote"])}”<br><small>— {h(FIELD_TEXT.get(e["field"], e["field"]))} field'
                        '</small></div>', unsafe_allow_html=True)
        if c.get('not_ranked_because'):
            st.markdown('**Not ranked:** ' + esc(c['not_ranked_because'])
                        + (f" (straight-line {c['distance_range_km'][0]}–{c['distance_range_km'][1]} km)"
                           if c.get('distance_range_km') else ''))
        if c.get('uncertainties'):
            st.markdown('**Not certain:** ' + esc('; '.join(c['uncertainties'])))
        if c.get('note'):
            st.caption(c['note'])

        loc = located(index, c)
        cols = st.columns(3)
        phone = c.get('phone')
        if phone:
            cols[0].link_button(f'Call {phone}', f"tel:{phone.replace(' ', '')}", use_container_width=True)
        else:
            cols[0].caption('No phone number in the records')
        if loc and loc[2]:
            cols[1].link_button('Directions · walking', directions_url(loc[0], loc[1], 'walking'), use_container_width=True,
                                help=f"Opens Google Maps to {c.get('name')} from your phone's own location.")
            cols[2].link_button('Directions · driving, no tolls', directions_url(loc[0], loc[1], 'driving'),
                                use_container_width=True,
                                help=f"Opens Google Maps to {c.get('name')}, avoiding tolls, from your phone's own location.")
        else:
            cols[1].caption('Location approximate: confirm the address by phone before travelling (no directions link).')

        if nested:
            if c.get('ask_when_calling'):
                st.caption('Ask when you call: ' + ' · '.join(c['ask_when_calling'][:2]))
            return
        with st.expander('Evidence, next step and sources'):
            if c.get('ask_when_calling'):
                st.markdown('**Ask when you call**  \n' + '  \n'.join(f'• {esc(q)}' for q in c['ask_when_calling']))
            for e in c.get('evidence', [])[1:]:
                st.markdown(f"> “{esc(e['quote'])}”  \n> — *{FIELD_TEXT.get(e['field'], esc(e['field']))}* field")
            if c.get('tier_reasons'):
                st.markdown('**Why this tier:** ' + esc('; '.join(c['tier_reasons'])))
            if c.get('why_ranked'):
                st.markdown('**Why this order:** ' + esc(c['why_ranked']))
            if c.get('sort_reason'):
                st.markdown('**Why here in this sort:** ' + esc(c['sort_reason']))
            text = cost_text(c.get('cost'))
            if text:
                st.markdown('**Payment:** ' + esc(text) + (f"  \n“{esc(c['cost']['quote'])}”" if c['cost'].get('quote')
                                                        and c['cost'].get('field') != 'operatorTypeId' else ''))
            pref = c.get('preference')
            if pref:
                st.markdown(f"**Preference score {pref['score']:.2f}** (a ranking weight from stated assumptions, "
                            'not a chance of treatment)')
                for comp in pref['components']:
                    value = 'n/a' if comp['value'] is None else f"{comp['value']:.2f} × weight {comp['weight']:.2f}"
                    st.markdown(f"- *{esc(comp['name'])}* ({value}): {esc(comp['reason'])}")
            for u in c.get('source_urls', []):
                st.markdown(f'- Source: {esc(u)}')
            if c.get('website'):
                st.markdown(f"- Website: {esc(c['website'])}")
            st.caption(f"Facility id {c.get('facility_id')} · location confidence: {c.get('location_confidence')} · "
                       f"distance basis: {c.get('distance_basis') or 'facility coordinates'}"
                       + (f" · merged listings: {', '.join(c['merged_ids'])}" if c.get('merged_ids') else ''))


def map_points(index, r):
    pts = []
    for c in r.get('results', []):
        loc = located(index, c)
        if loc:
            pts.append({'lat': loc[0], 'lon': loc[1], 'label': str(c.get('rank', len(pts) + 1)), 'name': c.get('name'),
                        'detail': f"{c.get('distance_km')} km straight-line", 'color': PRIMARY_RGB})
    for key, label in (('farther_stronger', '+'), ('nearest_beyond', 'N')):
        c = r.get(key)
        loc = located(index, c) if c else None
        if loc:
            pts.append({'lat': loc[0], 'lon': loc[1], 'label': label, 'name': c.get('name'),
                        'detail': f"{c.get('distance_km')} km straight-line", 'color': EXTRA_RGB})
    return pts


def render_map(index, r):
    import pydeck as pdk
    o = r['origin']
    pts = map_points(index, r)
    span = max([math.dist((o['lat'], o['lon']), (p['lat'], p['lon'])) * 111 for p in pts] + [o.get('precision_km') or 3, 2])
    zoom = max(3.5, min(13.0, 13.2 - math.log2(span)))
    origin = [{'lat': o['lat'], 'lon': o['lon'], 'radius': max(500, (o.get('precision_km') or 2) * 1000),
               'name': f"Search centre: {o['label']}", 'detail': f"approximate, ±{o.get('precision_km')} km"}]
    layers = [
        pdk.Layer('ScatterplotLayer', data=origin, get_position='[lon, lat]', get_radius='radius',
                  get_fill_color=[26, 95, 122, 28], get_line_color=[26, 95, 122, 140], stroked=True,
                  line_width_min_pixels=1, pickable=True),
        pdk.Layer('ScatterplotLayer', data=pts, get_position='[lon, lat]', get_radius=13, radius_units='pixels',
                  get_fill_color='color', get_line_color=[255, 255, 255], stroked=True, line_width_min_pixels=2,
                  pickable=True),
        pdk.Layer('TextLayer', data=pts, get_position='[lon, lat]', get_text='label', get_size=14,
                  get_color=[255, 255, 255], get_text_anchor="'middle'", get_alignment_baseline="'center'",
                  font_weight=700),
    ]
    st.pydeck_chart(pdk.Deck(layers=layers, map_provider='carto', map_style='light',
                             initial_view_state=pdk.ViewState(latitude=o['lat'], longitude=o['lon'], zoom=zoom),
                             tooltip={'text': '{name}\n{detail}'}), use_container_width=True)
    st.caption('Numbered pins match the list. The shaded circle is the search centre and its precision. '
               'Distances are straight-line, not road distance or travel time.')


def status_line(r, sort_mode):
    n = len(r.get('results', []))
    if n:
        what = f"{n} option{'s' if n > 1 else ''} with credible evidence within {r['band_km']} km"
    elif r.get('nearest_beyond'):
        far = r['nearest_beyond'].get('distance_km')
        what = (f"No facility with credible evidence within {BANDS_KM[-1]} km. The nearest one is "
                f"{far} km away (below): call before travelling.")
    else:
        what = 'No facility with credible evidence was found for this service.'
    review = r.get('review') or {}
    checks = review.get('checks', [])
    qc = f" · quality checks {sum(1 for c in checks if c.get('passed'))}/{len(checks)}" if checks else ''
    order = {'default': 'ordered by evidence, then distance', 'nearest': 'ordered by straight-line distance',
             'price': 'ordered by documented price'}[sort_mode]
    pc = (r.get('sort') or {}).get('price_comparison') or {}
    if sort_mode == 'price' and pc.get('ranked_by') == 'distance':
        order = 'ordered by distance: too few comparable prices to rank'
    return f'<div class="cm-status" role="status"><b>{h(what)}</b>' + (f' · {order}' if n else '') + f'{h(qc)}</div>'


def render_result(index, r, sort_mode, service):
    o = r['origin']
    st.markdown(f"**{esc(r['service_label'])}** near **{esc(o['label'])}** · search centre precision about "
                f"{o['precision_km']} km")
    if o.get('alternatives'):
        cols = st.columns(min(4, len(o['alternatives'])))
        for col, alt in zip(cols, o['alternatives']):
            col.button(f'Use {alt}', key=f'alt-{alt}', on_click=_set_place, args=(alt,))
    st.markdown(status_line(r, sort_mode), unsafe_allow_html=True)
    review = r.get('review')
    if review and not review.get('passed'):
        st.error('A quality check failed for this answer: ' + '; '.join(c['name'] for c in review['checks'] if not c['passed']))
    if r.get('action_advice'):
        st.info(f"**Next step:** {esc(r['action_advice'])}", icon='📞')
    sort = r.get('sort') or {}
    if sort_mode == 'price' and service in TIME_CRITICAL:
        st.warning('For an emergency, go to the nearest facility that can treat the patient. Sorting by price is meant '
                   'for care that can be planned.', icon='⚠️')
    if sort.get('safety_note'):
        st.warning(sort['safety_note'], icon='⚠️')
    if sort.get('stronger_option_nearby'):
        s = sort['stronger_option_nearby']
        st.caption(f"Also within reach: **{esc(s['name'])}** ({s['distance_km']} km) has Strong evidence. {esc(s.get('note', ''))}")
    if sort_mode == 'price':
        pc = sort.get('price_comparison') or {}
        st.caption((esc(pc['note']) + ' ' if pc.get('note') else '')
                   + 'Prices are quotes found on web pages: they may be out of date, for a package, or only for some patients. '
                   'Only quotes with the same unit are compared; an unknown price is not assumed high or low.')
    if (r.get('preferences') or {}).get('applied') and r.get('tradeoff_note'):
        st.caption(f"Trade-off: {esc(r['tradeoff_note'])}")

    left, right = st.columns([1.15, 1], gap='large')
    with left:
        for c in r.get('results', []):
            render_card(index, c, str(c.get('rank', '')), sort_mode)
        if r.get('farther_stronger'):
            st.markdown('**Farther away, but stronger evidence**')
            render_card(index, r['farther_stronger'], '+', sort_mode, extra=True)
        if r.get('nearest_beyond'):
            st.markdown('**Nearest facility with credible evidence**')
            render_card(index, r['nearest_beyond'], 'N', sort_mode, extra=True)
        if r.get('cost_unknown_options'):
            st.markdown('**Cost not documented in the record** (may still be free or covered; ask when calling)')
            for c in r['cost_unknown_options']:
                render_card(index, c, '', sort_mode, extra=True)
        for key, title in (('price_not_comparable', 'Price documented, but not comparable with the quotes above'),
                           ('price_unknown_nearby', 'Also within reach, price not documented'),
                           ('branch_unresolved', 'Not ranked: the record may mix several branches'),
                           ('location_uncertain', 'Not ranked: location uncertain')):
            if sort.get(key):
                with st.expander(f"{title} ({len(sort[key])})"):
                    for c in sort[key]:
                        render_card(index, c, '', sort_mode, extra=True, nested=True)
        if r.get('weak_nearby'):
            with st.expander(f"Mentioned nearby, but the evidence is weak ({len(r['weak_nearby'])}, not recommended)"):
                for c in r['weak_nearby']:
                    render_card(index, c, '', sort_mode, extra=True, nested=True)
    with right:
        if map_points(index, r):
            render_map(index, r)
        if r.get('service_scope'):
            st.markdown(f"**What the records can show.** {esc(r['service_scope'])}")
        for note in o.get('notes', []):
            st.caption(note)
        with st.expander('How we decided'):
            st.markdown(esc(r['method']))
            if r.get('preference_model'):
                st.markdown('**Preference model** (re-orders the same credible options)  \n'
                            + '  \n'.join(f"- {esc(k)}: {esc(v)}" for k, v in r['preference_model'].items()
                                          if k not in ('urgency', 'cost')))
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
            for chk in (review or {}).get('checks', []):
                st.markdown(f"{'✅' if chk.get('passed') else '❌'} {esc(chk.get('name'))}"
                            + (f" — {esc(chk.get('detail'))}" if chk.get('detail') else ''))
        st.caption(r['disclaimer'])


# ---- page ----------------------------------------------------------------------------------------------------

st.markdown(CSS, unsafe_allow_html=True)
st.title('Find care')
st.caption('For health workers and families in India: one service, one place, up to three facilities, and the evidence '
           'behind each one. Always call before travelling.')

try:
    index, info = get_index()
except Exception as exc:  # a data failure must never look like "no hospitals found"
    st.error(f'Could not load the facility data, so no search is possible right now.\n\n{exc}')
    st.stop()

labels = {spec['label']: key for key, spec in SERVICES.items()}
with st.form('search'):
    c1, c2 = st.columns([1, 1.4])
    service_label = c1.selectbox('Service needed', list(labels))
    c2.text_input('Where is the patient?', key='place', placeholder='City, district, 6-digit PIN code, or "lat, lon"')
    st.caption('Examples: ' + ' · '.join(EXAMPLES))
    with st.expander('Preferences (optional)'):
        urgency_options = {'Default: evidence first, then distance': 'default',
                           'Time-critical: every minute on the road counts': 'time_critical',
                           'Can travel further for better-prepared care': 'can_travel'}
        cost_options = {'Cost does not change the order': 'any',
                        'Prefer care documented as free, government-scheme or insured': 'low_cost'}
        urgency_label = st.radio('How urgent is it?', list(urgency_options), key='urgency')
        cost_label = st.radio('Cost', list(cost_options), key='cost')
    st.form_submit_button('Find care', type='primary')

place = (st.session_state.get('place') or '').strip()
if place:
    service = labels[service_label]
    sort_choices = [k for k, v in SORTS.items() if SUPPORTS[v]]
    t1, t2 = st.columns([1.4, 1])
    sort_label = t1.radio('Sort results', sort_choices, horizontal=True, key='sort')
    sort_mode = SORTS[sort_label]
    prefs = {'urgency': urgency_options[urgency_label], 'cost': cost_options[cost_label]}
    kwargs = {}
    if sort_mode == 'default':
        kwargs['preferences'] = prefs
    else:
        # The engine takes either preferences or a sort order, never both.
        kwargs['sort_mode'] = sort_mode
        if prefs != {'urgency': 'default', 'cost': 'any'}:
            t1.caption('Your preferences apply to the “Best evidence” order; this order ignores them.')
    if sort_mode == 'price':
        kwargs['max_extra_km'] = t2.slider('Extra distance you would travel for a lower price', 0, 100, 25, step=5,
                                           format='%d km', key='max_extra_km')
    if not SUPPORTS['price']:
        t2.caption('Sorting by listed price becomes available with the next engine update.')
    with st.spinner('Checking the evidence…'):
        result = recommend(index, service, place, **kwargs)
    if 'error' in result:
        st.error(result['error'])
    else:
        render_result(index, result, sort_mode, service)
else:
    st.info('Choose a service, type where the patient is, and press **Find care**.')

with st.sidebar:
    st.markdown('**Data**')
    st.caption(f"Source: {info['source']} · {info['facility_rows']:,} facilities · {info['pincode_rows']:,} PIN rows · "
               f"loaded in {info['load_seconds']} s, indexed in {info['index_seconds']} s")
    for failure in info.get('failed_sources', []):
        st.caption(f'Fallback used; failed: {failure}')
    st.markdown('**About**')
    st.caption('Suggestions come from public web listings compiled by the Virtue Foundation. A listing saying a facility '
               'offers a service is evidence, not proof. Prices are web quotes. Always call first.')
