"""NGO planning view. Streamlit discovers this page beside app/Find_care.py."""
from pathlib import Path
import json
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
import cm_style
from carematch.call_map import load_map

st.set_page_config(page_title='C-section verification map', layout='wide')
cm_style.apply()
cm_style.bar('Planning view for NGO coordinators')
st.title('Where should we call first?')
st.write('Explore how many more PIN areas could have a documented C-section facility within 50 km if the selected branches confirm on-site service.')

directory = ROOT / 'analysis'
files = ('pin_status', 'call_plan', 'call_candidates')
paths = [directory / f'c_section_{name}.csv' for name in files]
paths.append(directory / 'c_section_call_plan_summary.json')
k = st.radio('Verification call budget', [0, 3, 5, 10], index=1, horizontal=True)
need_file = directory / 'c_section_call_plan_need.csv'
OBJECTIVES = ['Most PIN areas', 'PIN areas where caesareans are rare']
objective = st.radio('What should each call add?', OBJECTIVES, horizontal=True, disabled=not need_file.is_file(),
                     help='"Most PIN areas" counts every PIN equally. "Where caesareans are rare" counts only PINs in '
                          'districts whose NFHS-5 caesarean rate is below 10%: WHO finds that up to about 10%, more '
                          'caesareans go with fewer maternal and newborn deaths.')
need = objective == OBJECTIVES[1] and need_file.is_file()
alternate = directory / 'c_section_call_plan_if_first_fails.csv'
first_failed = st.checkbox('The first branch answered no. Use the remaining calls.',
                           disabled=k == 0 or need or not alternate.is_file())
first_failed = first_failed and k > 0 and not need and alternate.is_file()
if first_failed:
    paths.append(alternate)
if need:
    paths.append(need_file)


@st.cache_data(show_spinner=False)
def read_snapshot(directory, versions, first_failed, need):
    return load_map(directory, first_failed, need)


try:
    versions = [(p.stat().st_mtime_ns, p.stat().st_size) for p in paths]
    points, calls, excluded = read_snapshot(directory, versions, first_failed, need)
    with paths[3].open(encoding='utf-8') as source:
        need_summary = json.load(source).get('need_plan') or {}
except FileNotFoundError as exc:
    st.info(f'Waiting for the planning snapshot. Missing file: {Path(exc.filename).name}')
    st.stop()
except (ValueError, TypeError, KeyError) as exc:
    st.error(f'The planning tables could not be reconciled. {exc}')
    st.stop()

available = k - int(first_failed)
chosen = calls[:available]
if first_failed:
    st.caption(f'One call spent. Up to {available} follow-up calls remain. Gains assume those branches confirm.')
gain = int(chosen[-1]['cumulative_gain']) if chosen else 0
frame = pd.DataFrame(points)
covered = int(frame['covered_now'].sum())
total = len(frame)
rare = frame['district_csection_pct'].notna() & (frame['district_csection_pct'] < 10)
cols = st.columns(3)
if need:
    waiting = int((rare & ~frame['covered_now']).sum())
    cols[0].metric('Low-caesarean PINs outside coverage now', f'{waiting:,}')
    cols[1].metric('Of these, added if confirmed', f'{gain:,}')
    cols[2].metric('Still outside documented coverage', f'{waiting-gain:,}')
    st.caption(f'{int(rare.sum()):,} of {total:,} reliable PINs lie in districts with an NFHS-5 caesarean rate below 10%. '
               'Districts without an NFHS match are not counted as low. Distances are straight-line from PIN centres.')
    budget = next((b for b in need_summary.get('by_budget', []) if b.get('k') == k), None)
    if budget and budget.get('need_plan_target_pins') == gain:
        st.write(f"Counting every PIN equally sends the calls to districts with a median caesarean rate of "
                 f"{need_summary.get('coverage_plan_median_district_csection_pct')}%; the first {k} of those calls reach "
                 f"{budget['coverage_plan_target_pins']} of these low-caesarean PINs. Counting need reaches {gain}.")
else:
    cols[0].metric('Covered in current records', f'{covered:,}')
    cols[1].metric('Additional PINs if confirmed', f'{gain:,}')
    cols[2].metric('Still outside documented coverage', f'{total-covered-gain:,}')
    st.caption(f'{total:,} unique PINs with reliable centres. {excluded:,} additional PINs have uncertain locations and are excluded. Distances are straight-line from PIN centres.')

baseline_file = directory / 'c_section_call_plan_baseline.csv'
if k and not first_failed and baseline_file.is_file():
    import csv
    with baseline_file.open(encoding='utf-8-sig', newline='') as source:
        comparison = next((row for row in csv.DictReader(source) if row.get('k') == str(k)), None)
    if comparison and comparison.get('greedy_new_pins') == str(gain) and comparison.get('denominator_pins') == str(total):
        st.write(f"With {k} calls, selecting branches by individual gain alone would add "
                 f"{comparison['topk_by_individual_gain_new_pins']} unique PINs. Accounting for overlap yields {gain}.")

labels = ['Outside documented coverage', 'Covered in current records', 'Additional if confirmed']
colours = ['#b7bbc3', '#2a78d6', '#eb6834']
frame['status'] = labels[0]
frame.loc[frame.covered_now, 'status'] = labels[1]
if need:
    # Show where the need is: uncovered PINs in low-caesarean districts, drawn above the other uncovered PINs.
    labels.insert(2, 'Outside coverage, caesarean rate below 10%')
    colours.insert(2, '#8e2f5a')
    frame.loc[rare & ~frame.covered_now, 'status'] = labels[2]
new = frame['rank'].between(1, len(chosen))
frame.loc[new, 'status'] = labels[-1]
frame['call'] = frame['rank'].where(new).astype('Int64')
focus = st.checkbox('Zoom to newly covered PINs', disabled=gain == 0)
view = frame[new] if focus and gain else frame
# Draw conditional gains last, so they remain visible in densely clustered areas.
view = view.assign(layer=view.status.map(dict(zip(labels, range(len(labels)))))).sort_values('layer')
fields = ['lon', 'lat', 'pin', 'district', 'state', 'status', 'call', 'nearest_credible_km', 'nearest_credible_tier',
          'nearest_facility_id', 'district_csection_pct']
st.vega_lite_chart(view[fields], {
    'height': 520,
    'projection': {'type': 'mercator'},
    'mark': {'type': 'circle', 'size': 19, 'opacity': 0.83},
    'encoding': {
        'longitude': {'field': 'lon', 'type': 'quantitative'},
        'latitude': {'field': 'lat', 'type': 'quantitative'},
        'color': {'field': 'status', 'type': 'nominal', 'title': None,
                  'scale': {'domain': labels, 'range': colours},
                  'legend': {'orient': 'bottom', 'columns': 1, 'labelLimit': 420}},
        'tooltip': [{'field': f, 'type': t, 'title': s} for f, t, s in (
            ('pin', 'nominal', 'PIN'), ('district', 'nominal', 'District'), ('state', 'nominal', 'State'),
            ('status', 'nominal', 'Coverage'), ('call', 'ordinal', 'Call rank'),
            ('nearest_credible_km', 'quantitative', 'Nearest documented facility (km)'),
            ('district_csection_pct', 'quantitative', 'District caesarean rate, NFHS-5 (%)'),
            ('nearest_credible_tier', 'nominal', 'Evidence tier'), ('nearest_facility_id', 'nominal', 'Facility ID'))]
    }
}, use_container_width=True)

if chosen:
    st.subheader('Call order and evidence')
    st.caption('Each call adds the largest remaining set of unique '
               + ('low-caesarean PINs' if need else 'PINs') + '. Overlapping PINs count once.')
    for c in chosen:
        lead = c['candidate']
        with st.expander(f"{c['rank']}. {c['name']} · +{c['marginal_gain']} unique PINs", expanded=c == chosen[0]):
            st.write(', '.join(v for v in (lead.get('branch'), lead.get('state')) if v))
            if need:
                st.write(f"Adds coverage in: {c['districts'].replace(' | ', ', ')}. District caesarean rate (median): "
                         f"{c['median_district_csection_pct']}%. Also reaches {c['other_new_pins']} other uncovered PINs.")
            st.write(f"Phone: {lead['phone']}")
            st.caption(f"Unverified C-section lead · Facility ID {c['facility_id']}")
            for field, quote in zip(lead['lead_fields'].split(' | '), lead['lead_quotes'].split(' | ')):
                st.text(f'{field} · {quote}')
            st.markdown('**Ask when calling**')
            for question in lead['call_questions'].split(' | '):
                st.write(question)
if len(chosen) < available:
    st.info(f'The published plan contains {len(chosen)} calls within this budget.')
st.caption('Existing coverage requires Strong or Moderate evidence. A branch with conflicting locations must be within 50 km at every plausible location. Confirm service and availability before referral.')
