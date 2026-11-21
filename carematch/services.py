"""Service vocabulary: what text counts as evidence for each service.

Patterns are case-insensitive regexes matched against single claim fragments (one JSON-array item).
  direct    - names the service itself ("Provides hemodialysis", "14 dialysis machines")
  related   - department / prerequisite terms that make the service plausible but do not prove it
  exclude   - contexts that make a direct hit a false positive (e.g. "dental trauma")
Specialty enum values (camelCase in `specialties`) are listed separately and only ever count as related.

Calibrated on the full facilities table on 2026-11-21; see docs/evidence_calibration.md.
"""

SERVICES = {
    'dialysis': {
        'label': 'Dialysis',
        'direct': [r'\b(ha?emo|peritoneal\s+)?dialy[sz](is|es)\b', r'\bartificial kidney\b', r'\bcrrt\b', r'\bcapd\b'],
        'related': [r'\bnephrolog', r'\bkidney transplant', r'\brenal (care|unit|replacement)'],
        'related_specialties': ['nephrology', 'pediatricNephrology', 'renalTransplantationUrology'],
        'exclude': [],
        'needs_inpatient': False,
        'ask': ['Is the dialysis unit running today, and is a slot free?',
                'Is it haemodialysis, peritoneal dialysis, or both?',
                'Is it free or covered under PM-JAY / the national dialysis programme?'],
    },
    'c_section': {
        'label': 'Emergency C-section',
        'direct': [r'\bca?esarean', r'\bc[- ]?sections?\b', r'\blscs\b', r'\bcemonc\b',
                   r'\bemergency obstetric (care|surgery)'],
        'related': [r'\bobstetric', r'\blabou?r (room|ward|suite)', r'\bmaternity\b', r'\bhigh[- ]risk pregnanc',
                    r'\bblood bank\b', r'\banaesthe|\banesthe'],
        'related_specialties': ['gynecologyAndObstetrics', 'obstetricsAndMaternityCare', 'obstetricsAndGynaecology',
                                'obstetricsAndGynecology', 'maternalFetalMedicineOrPerinatology', 'anesthesia'],
        'exclude': [r'\bveterinar'],
        'needs_inpatient': True,
        'ask': ['Can you do an emergency C-section right now (surgeon and anaesthetist on duty)?',
                'Is blood available on site?', 'Is there a newborn care unit if the baby needs it?'],
    },
    'nicu': {
        'label': 'NICU (newborn intensive care)',
        'direct': [r'\bnicu\b', r'\bneonatal intensive', r'\bnewborn intensive', r'\bsncu\b',
                   r'\bspecial newborn care', r'\blevel[- ](ii|iii|2|3)\b.{0,20}neonat'],
        'related': [r'\bneonat', r'\bincubator', r'\bradiant warmer', r'\bphototherapy', r'\bpicu\b', r'\bpaediatric icu|\bpediatric icu'],
        'related_specialties': ['neonatologyPerinatalMedicine', 'pediatricCriticalCareMedicine'],
        'exclude': [],
        'needs_inpatient': True,
        'ask': ['Is a NICU bed free right now?', 'Do you have a ventilator / CPAP for newborns?',
                'Is a paediatrician or neonatologist on duty 24 hours?'],
    },
    'trauma': {
        'label': 'Trauma care',
        'direct': [r'\btrauma\b', r'\bpolytrauma', r'\baccident (and|&) emergency', r'\baccident care\b', r'\btraumatology'],
        'related': [r'\bemergency\b', r'\bcasualty\b', r'\bicu\b', r'\bintensive care', r'\bneurosurg', r'\borthopa?edic', r'\bblood bank'],
        'related_specialties': ['emergencyMedicine', 'criticalCareMedicine', 'neurosurgery', 'orthopedicSurgery',
                                'burnAndTraumaPlasticSurgery', 'generalSurgery'],
        'exclude': [r'\bdental|\btooth|\bteeth|\bfacial|\bmaxillofacial|\beye\b|\bocular|\bpsycholog|\bemotional|\bptsd\b'
                    r'|\bbirth trauma|\bcounsel|\bnasal|\bnose\b|\bear\b|\bsports injur'],
        'needs_inpatient': True,
        'ask': ['Can you receive a road-accident patient now (surgeon, CT and blood available)?',
                'Is there an ICU bed free?', 'Do you have a neurosurgeon / orthopaedic surgeon on call?'],
    },
    'emergency': {
        'label': '24x7 emergency department',
        'direct': [r'\bemergency (department|room|ward|services?|care|unit|medicine|wing)', r'\bcasualty\b',
                   r'\baccident (and|&) emergency', r'\b24\s*[x×/*]\s*7 emergency', r'\bemergency 24\s*[x×/*]\s*7'],
        'related': [r'\bambulance', r'\b24\s*[x×/*]\s*7', r'\bicu\b', r'\bintensive care', r'\bround[- ]the[- ]clock'],
        'related_specialties': ['emergencyMedicine', 'criticalCareMedicine', 'pediatricEmergencyMedicine'],
        'exclude': [r'\bdental|\btooth|\bteeth|\beye\b|\bocular|\bcontracept|\bveterinar|\bpharmac'],
        'needs_inpatient': True,
        'ask': ['Is the emergency department open now, and is a doctor on duty?', 'Do you have an ambulance?'],
    },
    'burn': {
        'label': 'Burn care',
        'direct': [r'\bburns?\s+(unit|ward|care|centre|center|management|treatment|surgery|patients?|injur|icu|wound)',
                   r'\b(treatment|management|care|surgery) of burns?\b', r'\bburns? (and|&) (plastic|trauma|reconstruct)',
                   r'\bpost[- ]?burn', r'\bplastic surgery including burns'],
        'related': [r'\bplastic surg', r'\bskin graft', r'\breconstructive surg'],
        'related_specialties': ['burnAndTraumaPlasticSurgery', 'plasticSurgery', 'reconstructivePlasticSurgery'],
        'exclude': [r'\bburnout', r'\bheart ?burn', r'\bsun ?burn', r'\bacid burn|\brazor burn'],
        'needs_inpatient': True,
        'ask': ['Do you have a burn unit or burn ward with a free bed?', 'Is a plastic surgeon available?'],
    },
    'cardiac_surgery': {
        'label': 'Cardiac surgery',
        'direct': [r'\bcardiac surg', r'\bheart surg', r'\bopen[- ]heart', r'\bcabg\b', r'\bcoronary artery bypass',
                   r'\bcardio[- ]?thoracic', r'\bvalve (replacement|repair|surgery)', r'\bctvs\b'],
        'related': [r'\bcath(eteri[sz]ation)? ?lab', r'\bangioplast', r'\bangiograph', r'\bcardiolog', r'\bicu\b|\bccu\b'],
        'related_specialties': ['cardiacSurgery', 'cardiothoracicSurgery', 'interventionalCardiology', 'cardiology',
                                'pediatricCardiology', 'vascularSurgery'],
        'exclude': [],
        'needs_inpatient': True,
        'ask': ['Do you perform heart surgery (bypass / valve) on site, and when is the next slot?',
                'Is it covered under PM-JAY or a state scheme?'],
    },
    'mri': {
        'label': 'MRI scan',
        'direct': [r'\bmri\b', r'\bmagnetic resonance'],
        'related': [r'\bradiolog', r'\bct scan|\bct\b', r'\bimaging\b'],
        'related_specialties': ['radiology', 'diagnosticRadiology', 'neuroradiology', 'interventionalRadiology'],
        'exclude': [],
        'needs_inpatient': False,
        'ask': ['Is the MRI machine working today, and what is the waiting time?', 'What does a scan cost?'],
    },
    'ct_scan': {
        'label': 'CT scan',
        'direct': [r'\bct\b(?!\s*(?:g|scan(?:ning)? report))', r'\bcomputed tomography', r'\bcat scan', r'\b\d+[- ]slice'],
        'related': [r'\bradiolog', r'\bmri\b', r'\bimaging\b'],
        'related_specialties': ['radiology', 'diagnosticRadiology', 'neuroradiology'],
        'exclude': [r'\bct\s*simulator'],
        'needs_inpatient': False,
        'ask': ['Is the CT scanner working right now (including at night)?', 'What does a scan cost?'],
    },
}

# A direct hit in the same fragment as one of these is not an in-house claim.
INDIRECT = (r'\btie[- ]?up|\boutsourc|\breferr(al|ed|ing)\b|\brefer(s)? (patients )?to\b|\bpartner(ed|ship)?\b'
            r'|\bvia\b|\bthrough (a |an )?(partner|associate)|\bvisible in (the )?(photo|image)|\bphotos? (show|indicate)'
            r'|\bplanned\b|\bproposed\b|\bcoming soon\b|\bupcoming\b|\bunder construction\b|\bwill (be|soon)\b'
            r'|\bto be (started|launched|set up)\b|\bwas located\b|\bformerly\b|\bpreviously\b')

# Negation must sit right next to the service term (checked in a short window before / after the hit).
NEG_BEFORE = r'\b(no|without|lacks?|lacking|not|excluding|except|other than)\s+(\w+\s+){0,2}$'
NEG_AFTER = (r'^\W{0,3}(\w+\W+){0,3}?(is |are )?(not (available|offered|provided|done|performed)|unavailable'
             r'|discontinued|closed (down|permanently)|suspended)\b')

# A fragment that enumerates many departments ("Specialties include A, B, C, D ...") names the
# service only as a list item: it counts as a direct claim for 'moderate' but not as corroboration.
LIST_MIN_COMMAS = 4

# Facility types that cannot plausibly provide any of these services.
INCOMPATIBLE_TYPES = {'dentist', 'pharmacy', 'farmacy', 'doctor'}
# facilityTypeId is often just "clinic"; a name like "Patra Dental Clinic" tells us more.
SPECIALTY_NAME = (r'\b(dental|dentist|dentistry|teeth|tooth|orthodont|eye|netra|vision|ophthalm|optical|skin|derma'
                  r'|cosmetic|hair|homoeo|homeo|ayurved|unani|siddha|physiotherap|rehab|de-?addiction|nasha mukti'
                  r'|psychiatr|pathology lab|diagnostic lab|laborator)\w*\b')


def service_keys():
    return list(SERVICES)


SERVICE_ALIASES = {
    'emergency': 'emergency', 'er': 'emergency', 'casualty': 'emergency', 'emergency room': 'emergency',
    'heart surgery': 'cardiac_surgery', 'bypass surgery': 'cardiac_surgery',
    'ct': 'ct_scan', 'ct scan': 'ct_scan', 'cat scan': 'ct_scan',
    'c section': 'c_section', 'caesarean': 'c_section', 'cesarean': 'c_section', 'high-risk delivery': 'c_section',
    'burns': 'burn', 'burn care': 'burn', 'burn unit': 'burn',
    'newborn icu': 'nicu', 'neonatal icu': 'nicu', 'kidney dialysis': 'dialysis', 'accident': 'trauma',
}


def resolve_service(text):
    """Map free text ('C-section', 'dialysis', 'nicu') to a service key, or None."""
    import re
    t = ' '.join((text or '').strip().lower().replace('_', ' ').split())
    if t.replace(' ', '_') in SERVICES:
        return t.replace(' ', '_')
    if t in SERVICE_ALIASES:
        return SERVICE_ALIASES[t]
    for key, spec in SERVICES.items():
        if t == spec['label'].lower() or any(re.search(p, t) for p in spec['direct']):
            return key
    return None
