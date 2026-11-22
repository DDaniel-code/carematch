"""Free-text need -> supported service + urgency (a transparent condition lexicon, not a diagnosis).

A community health worker types what is happening ("heavy bleeding after delivery", "accident mein sar par chot").
interpret_need() maps it to one of the nine services and a default urgency so the existing recommender can run.
Nothing here ranks facilities or changes the evidence rules.

Rules
  - Phrase lexicon in English and common romanized Hindi; every match is quoted back from the user's own words.
  - A trigger preceded by an English negation ("no bleeding", "not a burn") is ignored.
  - Several conditions: the most severe becomes the suggestion; the others are listed as "also possible". When two
    red-flag conditions point to different services the status is "ambiguous" and the user must confirm.
  - No match: status "no_match"; the app asks the user to pick a service. Never a guess.
  - Red flags put an emergency-call prompt (108; 102 for pregnant women and newborns in most states) first.
Romanized Hindi spellings vary; the lexicon covers common forms and should be reviewed by a Hindi speaker.
"""
import re

from .services import SERVICES

DISCLAIMER = ('This matches your description to a type of service so we can search. It is not a diagnosis or medical '
              'advice. You can change the service and urgency before searching.')
CALL_NOW = '108 (ambulance); 102 for pregnant women and newborns in most states'

PREGNANCY = r'(pregnan|delivery|deliveries|childbirth|after birth|labou?r|postpartum|post[- ]partum|garbh|prasav|delivery ke)'

# Each condition: alternatives are a regex, or a tuple of regexes that must all match (e.g. bleeding + pregnancy).
CONDITIONS = [
    {'id': 'obstructed_labour', 'label': 'prolonged or obstructed labour', 'service': 'c_section', 'also': ['emergency'],
     'urgency': 'time_critical', 'red_flag': True,
     'patterns': [r'\b(obstructed|prolonged|difficult|stuck) (labou?r|delivery)', r'\blabou?r (pains? )?(for|since) (many|\d+) hours',
                  r'\bbaby (is )?(stuck|not coming out)', r'\bbreech\b', r'\bcord (is )?(prolapse|coming out)',
                  r'\bprasav (peeda|pida|dard)\b.{0,30}\b(der|ghante|ghanton)', r'\bbach(ch)?a (atak|phas|fans)',
                  r'\b(dard|peeda) (bahut der|kai ghante|kai ghanton)']},
    {'id': 'obstetric_haemorrhage', 'label': 'heavy bleeding in pregnancy or after delivery', 'service': 'c_section',
     'also': ['emergency'], 'urgency': 'time_critical', 'red_flag': True,
     'patterns': [r'\bpost[- ]?partum ha?emorrhage', r'\bpph\b', r'\bantepartum ha?emorrhage',
                  (r'\b(bleeding|haemorrhage|hemorrhage|blood loss)\b', PREGNANCY),
                  (r'\b(khoon|khun)\b.{0,25}\b(beh|bah|nikal|ruk nahi|zyada|bahut)', PREGNANCY)]},
    {'id': 'eclampsia', 'label': 'fits or very high blood pressure in pregnancy', 'service': 'c_section',
     'also': ['emergency'], 'urgency': 'time_critical', 'red_flag': True,
     'patterns': [r'\b(pre[- ]?)?eclampsia\b', (r'\b(fits?|seizures?|convulsions?|daure?|jhatke)\b', PREGNANCY)]},
    {'id': 'newborn_distress', 'label': 'newborn in distress or born too early', 'service': 'nicu', 'also': ['emergency'],
     'urgency': 'time_critical', 'red_flag': True,
     'patterns': [r'\b(baby|newborn|infant)\b.{0,25}\b(not breathing|blue|not crying|gasping|very weak)',
                  r'\bpremature (baby|birth|delivery)\b', r'\bpre[- ]?term (baby|birth)\b', r'\bborn (too )?early\b',
                  r'\blow birth ?weight\b', r'\bnavjaat\b', r'\bbach(ch)?a\b.{0,20}\bsaans nahi',
                  r'\bsamay se pehle (paida|janam|janm)', r'\b(7|seven|8|eight) months? (baby|delivery)\b']},
    {'id': 'road_accident_head_injury', 'label': 'road accident or head injury', 'service': 'trauma', 'also': ['ct_scan'],
     'urgency': 'time_critical', 'red_flag': True,
     'patterns': [r'\b(road|car|bike|motorbike|scooter|bus|truck|auto) accident\b', r'\bhit by (a )?(car|bus|truck|bike|vehicle)',
                  r'\bhead injury\b', r'\binjur(y|ed) (to|on) (the )?head\b', r'\bunconscious after (a )?(fall|accident)',
                  r'\bdurghatna\b', r'\b(sar|sir) (par|pe|mein) chot\b', r'\baccident ho gaya\b', r'\bfell from (a )?(height|roof|building)']},
    {'id': 'fracture', 'label': 'broken bone (conscious, not bleeding heavily)', 'service': 'trauma', 'also': [],
     'urgency': 'default', 'red_flag': False,
     'patterns': [r'\bfracture[sd]?\b', r'\bbroken (leg|arm|bone|hand|wrist|ankle|hip)\b', r'\bhaddi (toot|tut)']},
    {'id': 'burns', 'label': 'burn or scald', 'service': 'burn', 'also': ['emergency'], 'urgency': 'time_critical',
     'red_flag': True,
     'patterns': [r'(?<!heart)(?<!sun)\bburn(s|ed|t)?\b', r'\bscald(ed|s)?\b', r'\bacid attack\b', r'\bfire injur',
                  r'\b(jal|jhulas) (gaya|gayi|gaye)\b', r'\baag (se|mein|lag)\b']},
    {'id': 'chest_pain', 'label': 'chest pain or suspected heart attack', 'service': 'emergency', 'also': ['cardiac_surgery'],
     'urgency': 'time_critical', 'red_flag': True,
     'patterns': [r'\bchest pain\b', r'\bpain in (the )?chest\b', r'\bheart attack\b', r'\bcardiac arrest\b',
                  r'\b(seene|chhati|chhaati) (mein|me) dard\b', r'\bdil ka daura\b'],
     'note': 'Heart attacks need an emergency department with a cath lab; the data has no cath-lab service, so we search '
             'emergency care. Ask about a cath lab when you call.'},
    {'id': 'stroke', 'label': 'suspected stroke', 'service': 'emergency', 'also': ['ct_scan'], 'urgency': 'time_critical',
     'red_flag': True,
     'patterns': [r'\bstroke\b', r'\bface (is )?(drooping|droop|twisted)', r'\bsudden(ly)? (weakness|numbness|paralysis)',
                  r'\bweakness (on|in) one side', r'\bslurred speech\b', r'\bcan.?t speak (suddenly|properly)',
                  r'\blakwa\b|\blakva\b', r'\b(muh|munh) (tedha|terha)'],
     'note': 'Stroke care needs a CT scan quickly; ask whether CT is working now when you call.'},
    {'id': 'bite_or_poisoning', 'label': 'snake bite or poisoning', 'service': 'emergency', 'also': [], 'urgency': 'time_critical',
     'red_flag': True,
     'patterns': [r'\bsnake ?bite\b', r'\bbitten by (a )?snake', r'\bpoison(ing|ed)?\b', r'\bswallowed (pesticide|poison|kerosene|acid)',
                  r'\bpesticide\b', r'\b(saanp|sanp|saap) (ne )?(kaat|kat)', r'\b(zeher|zehar|zahar)\b'],
     'note': 'Ask whether anti-snake venom is available when you call.'},
    {'id': 'kidney_failure', 'label': 'kidney failure / needs dialysis', 'service': 'dialysis', 'also': [],
     'urgency': 'can_travel', 'red_flag': False,
     'patterns': [r'\b(kidney|renal) failure\b', r'\bdialysis\b', r'\b(creatinine|urea) (is )?(high|raised|very high)',
                  r'\bckd\b', r'\b(kidney|gurde?) (kharab|fail)'],
     'note': 'Breathlessness, confusion or no urine after a missed dialysis session is an emergency: call 108.'},
    {'id': 'heart_surgery_advised', 'label': 'heart surgery advised', 'service': 'cardiac_surgery', 'also': [],
     'urgency': 'default', 'red_flag': False,
     'patterns': [r'\b(bypass|cabg|valve replacement|valve surgery|open heart|heart surgery|angioplasty)\b',
                  r'\bbypass (karwana|karana)\b']},
    {'id': 'imaging_mri', 'label': 'MRI scan advised', 'service': 'mri', 'also': [], 'urgency': 'default', 'red_flag': False,
     'patterns': [r'\bmri\b', r'\bmagnetic resonance\b']},
    {'id': 'imaging_ct', 'label': 'CT scan advised', 'service': 'ct_scan', 'also': [], 'urgency': 'default', 'red_flag': False,
     'patterns': [r'\bct\b(?: ?scan)?', r'\bcat scan\b', r'\bcomputed tomography\b']},
]
NEGATION = re.compile(r'\b(no|not|without|denies|denied|never|ruled out)\s+(\w+\s+){0,2}$', re.I)
# A negation does not reach across "but", "and", "however" or punctuation: "no bleeding but labour for 20 hours".
SCOPE_BREAK = re.compile(r'[,.;:!?]|\b(but|and|however|though|although|lekin|par|aur)\b', re.I)
URGENCY_RANK = {'time_critical': 0, 'default': 1, 'can_travel': 2}

_compiled = []
for cond in CONDITIONS:
    alts = []
    for alt in cond['patterns']:
        alts.append(tuple(re.compile(p, re.I) for p in alt) if isinstance(alt, tuple) else (re.compile(alt, re.I),))
    _compiled.append((cond, alts))


def _clean(text):
    return ' '.join((text or '').replace('’', "'").split())


def _negated(text, start):
    prefix = text[:start][-40:]
    breaks = list(SCOPE_BREAK.finditer(prefix))
    if breaks:
        prefix = prefix[breaks[-1].end():]
    return bool(NEGATION.search(prefix))


def _match(cond_alts, text):
    """First (start, end) span for a condition, or None. For a tuple alternative the span is the first regex's match."""
    for alt in cond_alts:
        spans = []
        for rx in alt:
            m = next((m for m in rx.finditer(text) if not _negated(text, m.start())), None)
            if not m:
                break
            spans.append(m)
        else:
            start, end = min(m.start() for m in spans), max(m.end() for m in spans)
            # quote the whole phrase ("heavy bleeding after delivery") when the parts are close together
            return (start, end) if end - start <= 70 else (spans[0].start(), spans[0].end())
    return None


def interpret_need(text):
    """Map a free-text description to {status, service, urgency, matched, also_possible, red_flag, ...}."""
    raw = _clean(text)
    base = {'input': raw, 'disclaimer': DISCLAIMER}
    if not raw:
        return {**base, 'status': 'no_match', 'service': None, 'urgency': None, 'matched': [], 'also_possible': [],
                'red_flag': False, 'understood_as': 'Please describe the situation or choose a service.'}
    hits = []
    for order, (cond, alts) in enumerate(_compiled):
        span = _match(alts, raw)
        if span:
            hits.append((cond, span, order))
    if not hits:
        return {**base, 'status': 'no_match', 'service': None, 'urgency': None, 'matched': [], 'also_possible': [],
                'red_flag': False,
                'understood_as': 'We could not match this to one of the nine services. Please choose a service from the list.'}
    # imaging words alone ("needs CT") only count when nothing more specific was said ("head injury, needs CT")
    specific = [h for h in hits if not h[0]['id'].startswith('imaging_')]
    if specific:
        hits = specific
    hits.sort(key=lambda h: (not h[0]['red_flag'], URGENCY_RANK[h[0]['urgency']], h[2]))
    top = hits[0][0]
    matched = [{'condition': c['label'], 'condition_id': c['id'], 'phrase': raw[s:e], 'service': c['service']}
               for c, (s, e), _ in hits]
    also = []
    for c, _, _ in hits:
        for s in [c['service']] + c['also']:
            if s != top['service'] and s not in also:
                also.append(s)
    red = any(c['red_flag'] for c, _, _ in hits)
    red_services = {c['service'] for c, _, _ in hits if c['red_flag']}
    status = 'ambiguous' if len(red_services) > 1 else 'matched'
    quoted = '; '.join(f"“{m['phrase']}” → {m['condition']}" for m in matched)
    understood = (f"From your words {quoted}: searching for {SERVICES[top['service']]['label']}"
                  f" ({'time-critical' if top['urgency'] == 'time_critical' else 'can travel further' if top['urgency'] == 'can_travel' else 'default order'}).")
    if status == 'ambiguous':
        understood += ' More than one emergency was described; please confirm which service to search first.'
    notes = [c['note'] for c, _, _ in hits if c.get('note')]
    return {**base, 'status': status, 'service': top['service'], 'service_label': SERVICES[top['service']]['label'],
            'urgency': top['urgency'], 'matched': matched, 'also_possible': also, 'red_flag': red,
            'call_now': CALL_NOW if red else None, 'notes': notes, 'understood_as': understood}
