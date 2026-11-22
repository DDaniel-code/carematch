"""Browse held-out model leads and their underlying facility text."""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cm_style

st.set_page_config(page_title='Service verification leads', layout='wide')
cm_style.apply()
cm_style.bar('Planning view for NGO coordinators')
st.title('Which facilities merit a C-section verification call?')
st.write('These records resemble facilities with documented C-section service. A coordinator can use the cited details to plan a call and verify the branch, service and current availability.')
folder = Path(__file__).resolve().parents[2] / 'analysis'
try:
    leads = pd.read_csv(folder / 'c_section_leads.csv', dtype=str, keep_default_na=False)
    with (folder / 'c_section_lead_model_metrics.json').open() as source:
        evaluation = json.load(source)
except (OSError, ValueError) as exc:
    st.error(f'Verification model output unavailable: {exc}')
    st.stop()

state = st.selectbox('State', ['All India'] + sorted(s for s in leads.state.unique() if s))
view = leads if state == 'All India' else leads[leads.state == state]
st.caption(f'{len(view)} leads in view · ordered by model score within the national list')
if len(view):
    facility = st.selectbox('Inspect a lead', view.index, format_func=lambda i: f"#{view.loc[i,'rank']} · {view.loc[i,'name']} · {view.loc[i,'city']}")
    record = view.loc[facility]
    st.write(f"Current evidence: {record.current_c_section_tier} · Phone: {record.phone or 'unknown'}")
    st.write(record.current_evidence_note)
    st.subheader('Why this record was selected')
    for reason in record.reasons.split(' | '):
        st.write(reason)
    st.caption(f'Facility ID {record.facility_id}')
    st.text(record.cited_text or 'No text excerpt in the exported model output.')
    st.write('Ask the branch whether it performs C-sections on site, which team is available, and how to arrange a referral.')

with st.expander('Model validation'):
    model = evaluation['held_out']['model']
    base = evaluation['held_out']['baseline_hospital_then_specialties']
    st.write('Validation asks how well the model identifies Strong documentation in held-out regions. Actual provision requires independent confirmation.')
    st.table(pd.DataFrame([model, base], index=['Model', 'Simple baseline'])[['roc_auc', 'pr_auc']])
