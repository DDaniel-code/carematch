"""Service-price evidence: documented patient prices for one service, quoted verbatim, never inferred.

A price is read only from a single claim fragment that (1) names the service itself and (2) states an amount in INR.
Each amount is classified before it can be used:
  patient price        what the patient is charged: exact, range, upper bound ("Rs. 350 or less"), lower bound
                       ("starting at"), or explicitly free
  insurer coverage     a scheme or insurer limit ("covers up to INR 5 lakh per family under PM-JAY"): not a price
  capital / equipment  what the facility spent ("machines worth Rs. 40 lakh", "built at a cost of 4.38 crore"): not a price

Never inferred: a public operator is not "free"; a package is not "per session"; an equipment cost is not a patient fee;
one quote is not "the cheapest". Prices are compared only when service, unit and conditions match (see comparable()).
"""
import re

from .services import SERVICES
from .textutil import fragments, normalize, text

FIELDS = ('procedure', 'capability', 'equipment', 'description')

AMOUNT = re.compile(
    r'(?:₹|\brs\.?|\binr\b|\brupees?\b)\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr\b|k\b)?'
    r'|(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)?\s*(?:rupees|/-|\binr\b)', re.I)
CAPITAL = re.compile(r'\bworth\b|\bcost of\b|\bbuilt at\b|\bbudget|\ballocat|\binvest|\bestimated cost|\bproject\b'
                     r'|\bsanction|\bgrant(ed)?\b|\bdonat|\bpurchase|\bprocured|\brestoration|\binaugurat|\bfoundation stone'
                     r'|\bconstruct|\bcapital|\bturnover|\brevenue|\bfunds?\b|\bcrores?\b|\bcr\b', re.I)
INSURER = re.compile(r'\bcovers?\b.{0,20}\bup ?to\b|\bcoverage\b|\bcover of\b|\bsum insured|\bper family\b|\bper year\b'
                     r'|\bpm-?jay\b|\bayushman|\bscheme benefit|\bbenefits? (of |up ?to)|\binsur|\bcashless|\bclaim', re.I)
UPPER = re.compile(r'\bor less\b|\bup ?to\b|\bmax(imum|\.)?\b|\bnot (more|exceeding) than\b|\bnot exceeding\b|\bbelow\b'
                   r'|\bunder\b|\bwithin\b|\bat most\b', re.I)
LOWER = re.compile(r'\bstart(s|ing)?( at| from)?\b|\bfrom\b|\bonwards\b|\bminimum\b|\bat least\b|\band above\b', re.I)
RANGE = re.compile(r'\d\s*(?:-|–|to)\s*(?:₹|rs\.?|inr)?\s*\d', re.I)
FREE = re.compile(r'\bfree of (cost|charge)\b|\bfree (dialysis|treatment|of charges)\b|\bat no cost\b|\bwithout (any )?charge', re.I)
DISCOUNT = re.compile(r'\b(regular|original|mrp|actual) (price|rate|cost)\b|\b\d+% off\b|\bdiscount', re.I)
UNITS = [('per_session', r'\bper (session|sitting|cycle)\b|/\s*session\b|\beach session\b'),
         ('per_scan', r'\bper (scan|study|test|investigation)\b|/\s*scan\b'),
         ('per_day', r'\bper (day|night|bed[- ]day)\b|/\s*day\b'),
         ('per_procedure', r'\bper (procedure|surgery|operation|delivery)\b'),
         ('per_month', r'\bper month\b|\bmonthly\b|/\s*month\b'),
         ('package', r'\bpackage\b')]
CONDITIONS = [('concessional / subsidised rate', r'\bconcession(al|ary)?\b|\bsubsidi[sz]ed\b|\bcharitable\b|\bfor the (poor|needy)\b|\bbpl\b'),
              ('discounted offer', DISCOUNT.pattern),
              ('scheme / insurance condition', r'\bunder\b.{0,30}\b(scheme|yojana|pm-?jay|ayushman|insurance|esi|cghs)\b'),
              ('inclusions stated', r'\binclu(ding|sive of|des)\b'),
              ('dated price', r'\bas of (19|20)\d\d\b|\bin (19|20)\d\d\b')]


def _amount(num, mult):
    value = float(num.replace(',', ''))
    m = (mult or '').lower()
    if m.startswith(('lakh', 'lac')):
        value *= 1e5
    elif m.startswith(('crore', 'cr')):
        value *= 1e7
    elif m == 'k':
        value *= 1e3
    return int(round(value))


RANGE_TAIL = re.compile(r'\s*(?:-|–|to)\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|k\b)?', re.I)


def amounts(fragment):
    out = []
    for m in AMOUNT.finditer(fragment):
        num, mult = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        if num and re.search(r'\d', num):
            out.append((_amount(num, mult), m.start(), m.end()))
            tail = RANGE_TAIL.match(fragment, m.end())       # "Rs 1,200 - 1,800": second number has no currency sign
            if tail and not any(t[1] == tail.start(1) for t in out):
                out.append((_amount(tail.group(1), tail.group(2) or mult), tail.start(1), tail.end()))
    return sorted(set(out), key=lambda t: t[1])


def classify(fragment):
    """(kind, details) for one fragment that contains an amount; kind in patient_price / insurer_coverage /
    capital_or_equipment."""
    found = amounts(fragment)
    if not found:
        return None
    if CAPITAL.search(fragment) and not re.search(r'\bcharge|\bfee|\bper (session|scan|visit)|\bpriced|\brate', fragment, re.I):
        return 'capital_or_equipment', {'amounts': [a for a, _, _ in found]}
    if INSURER.search(fragment) and not re.search(r'\bcharge[sd]?\b|\bpriced\b|\bfee\b|\bper session\b', fragment, re.I):
        return 'insurer_coverage', {'amounts': [a for a, _, _ in found]}
    first = found[0]
    window = fragment[max(0, first[1] - 25):first[2] + 15]
    if len(found) >= 2 and RANGE.search(fragment[found[0][1]:found[1][2]]) and not DISCOUNT.search(fragment):
        bound, lo, hi = 'range', min(found[0][0], found[1][0]), max(found[0][0], found[1][0])
    elif UPPER.search(window):
        bound, lo, hi = 'upper_bound', None, first[0]
    elif LOWER.search(window):
        bound, lo, hi = 'lower_bound', first[0], None
    else:
        bound, lo, hi = 'exact', first[0], first[0]
    unit = next((u for u, p in UNITS if re.search(p, fragment, re.I)), 'unspecified')
    conditions = [label for label, p in CONDITIONS if re.search(p, fragment, re.I)]
    return 'patient_price', {'bound': bound, 'amount_min_inr': lo, 'amount_max_inr': hi, 'unit': unit,
                             'conditions': conditions}


def price_evidence(row, service):
    """(price_info or None, context list). price_info is the single best documented patient price for the service;
    context lists insurer / capital amounts that are NOT prices (shown so they are never mistaken for one)."""
    direct = [re.compile(p, re.I) for p in SERVICES[service]['direct']]
    prices, context = [], []
    for field in FIELDS:
        for frag in fragments(row.get(field)):
            if not any(p.search(frag) for p in direct):
                continue
            if FREE.search(frag) and not amounts(frag):
                prices.append({'kind': 'patient_price', 'bound': 'free', 'amount_min_inr': 0, 'amount_max_inr': 0,
                               'unit': 'unspecified', 'conditions': [l for l, p in CONDITIONS if re.search(p, frag, re.I)],
                               'scope': service, 'field': field, 'quote': frag})
                continue
            c = classify(frag)
            if not c:
                continue
            kind, d = c
            if kind == 'patient_price':
                prices.append({'kind': kind, **d, 'scope': service, 'field': field, 'quote': frag})
            else:
                context.append({'kind': kind, 'amounts_inr': d['amounts'], 'field': field, 'quote': frag,
                                'note': 'not a patient price'})
    order = {'exact': 0, 'range': 1, 'upper_bound': 2, 'lower_bound': 3, 'free': 4}
    prices.sort(key=lambda p: (order[p['bound']], p['unit'] == 'unspecified', len(p['quote'])))
    info = prices[0] if prices else None
    if info:
        info = {**info, 'currency': 'INR', 'other_price_quotes': len(prices) - 1}
    return info, context


def interval(info):
    """[low, high] in INR for comparison; None means unbounded on that side."""
    return info['amount_min_inr'], info['amount_max_inr']


def comparable(a, b):
    """Two price_info dicts can be compared only for the same service and the same stated unit (never 'unspecified')."""
    return (a and b and a['scope'] == b['scope'] and a['unit'] == b['unit'] and a['unit'] != 'unspecified'
            and a['bound'] != 'free' and b['bound'] != 'free')


def surely_cheaper(a, b):
    """True only if every price a allows is below every price b allows (e.g. '<= 350' vs exactly 500)."""
    a_hi, b_lo = a['amount_max_inr'], b['amount_min_inr']
    return a_hi is not None and b_lo is not None and a_hi < b_lo
