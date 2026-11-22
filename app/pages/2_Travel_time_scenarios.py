"""Time-budget exploration using an explicitly assumed distribution of trips."""
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
import cm_style
from carematch.travel_scenario import arrival_share

st.set_page_config(page_title='C-section travel scenarios', layout='wide')
cm_style.apply()
cm_style.bar('Planning view for NGO coordinators')
st.title('Could the trip fit the time budget?')
st.write('Explore travel to branches with documented C-section service from each PIN centre. '
         'Percentages are probabilities under the travel assumptions below. Reception, treatment and outcomes are unmeasured.')


@st.cache_data
def load(paths, timestamps):
    pins = pd.read_csv(paths[0], dtype={'pin': str})
    facilities = pd.read_csv(paths[1], dtype=str)
    if (pins['pin'].duplicated().any() or pins.isna()[['lat','lon','strong_km','moderate_km']].any().any()
            or not all(pins[t+'_id'].isin(facilities.facility_id).all() for t in ('strong','moderate'))):
        raise ValueError('Incomplete or inconsistent travel snapshot')
    return pins, facilities


paths = tuple(ROOT / 'analysis' / f'travel_{s}.csv' for s in ('pins', 'facilities'))
try:
    data, facilities = load(paths, tuple(p.stat().st_mtime_ns for p in paths))
except (OSError, ValueError) as exc:
    st.error(f'Travel snapshot unavailable: {exc}')
    st.stop()

state = st.selectbox('Region', ['All India'] + sorted(data.state.dropna().unique()))
if state != 'All India':
    data = data[data.state == state].copy()
minutes = st.slider('Time from departure preparation to arrival (minutes)', 15, 240, 60, 15)
speed = st.slider('Assumed middle travel speed (km/h)', 15, 75, 40, 5)
delay = st.slider('Time to arrange departure (minutes)', 0, 90, 15, 5)
speeds = (speed-10, speed, speed+10)
detours = (1.2, 1.4, 1.6)
st.caption(f'Nine equally likely hypothetical trips combine speeds of {speeds[0]}, {speed}, {speeds[2]} km/h '
           'with road distances of 1.2, 1.4 or 1.6 times the straight-line distance. '
           'Each trip includes the selected departure delay. These settings are illustrative.')
joint = st.checkbox('Explore assumed on-site service availability')
weights = {'strong': 1.0, 'moderate': 1.0}
if joint:
    st.caption('Choose hypothetical confirmation rates for each evidence tier. The dataset has no measured rates. '
               'The model assumes confirmation is independent of the trip conditions and selects the branch with the highest joint scenario probability.')
    for tier in weights:
        weights[tier] = st.slider(f'Assumed service availability for {tier.title()} evidence (%)', 0, 100, 100, 5) / 100
for tier in weights:
    data[tier+'_arrival'] = [arrival_share(km, minutes, speeds, detours, delay) for km in data[tier+'_km']]
ss = data.strong_arrival * weights['strong']
ms = data.moderate_arrival * weights['moderate']
use_strong = (ss > ms) | ((ss == ms) & (data.strong_km <= data.moderate_km))
data['km'] = data.strong_km.where(use_strong, data.moderate_km)
data['facility_id'] = data.strong_id.where(use_strong, data.moderate_id)
data['arrival'] = data.strong_arrival.where(use_strong, data.moderate_arrival)
data['scenario'] = ss.where(use_strong, ms)
data = data.merge(facilities, on='facility_id', validate='many_to_one')
if not joint:
    st.caption('Each PIN uses its closest eligible branch. Eligibility requires Strong or Moderate service evidence and a usable location.')
label = 'Arrive + service available' if joint else 'Within budget'
st.write(f'{int((data.arrival == 1).sum()):,} of {len(data):,} reliable PINs in view fit the selected branch trip into all nine travel scenarios.')
st.vega_lite_chart(data[['lat','lon','pin','district','scenario','km','name','tier']], {
    'height': 490, 'projection': {'type':'mercator'}, 'mark': {'type':'circle','size':20},
    'encoding': {
        'longitude': {'field':'lon','type':'quantitative'}, 'latitude': {'field':'lat','type':'quantitative'},
        'color': {'field':'scenario','type':'quantitative','title':label,'scale':{'domain':[0,1],'scheme':'viridis'},'legend':{'format':'.0%'}},
        'tooltip':[{'field':'pin','title':'PIN'}, {'field':'district'}, {'field':'name','title':'Branch'},
                   {'field':'km','type':'quantitative','format':'.1f'}, {'field':'tier'},
                   {'field':'scenario','type':'quantitative','format':'.0%','title':label}]
    }
}, use_container_width=True)
pin = st.text_input('Inspect the evidence for a six-digit PIN in this region')
if pin:
    hit = data[data.pin == pin.strip()]
    if hit.empty:
        st.info('No reliable centre for this PIN in the selected region.')
    else:
        row = hit.iloc[0]
        st.subheader(str(row['name']))
        st.write(f"{row.km:.1f} km straight-line · {row.tier} evidence · {round(9*row.arrival)} of 9 trips within budget")
        if joint:
            st.write(f"Under your assumptions: {row.arrival:.1%} within budget × {weights[row.tier]:.0%} service available = {row.scenario:.1%}.")
        st.text(row.quote)
        st.caption(f"Source: facilities.{row.field} · {row.facility_id}")
st.caption('Locations with conflicting signals use the farthest plausible coordinate for each branch. '
           'Records flagged for mixing branches or institutions are excluded. '
           'This planning view assumes a usable road connection. Water crossings, traffic, dispatch and bed availability require local verification.')
