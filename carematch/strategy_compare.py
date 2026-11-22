"""Explain how three ranking rules change the first option for exactly the same search."""

from .recommend import recommend


ORDERS = {'default': 'Best evidence', 'nearest': 'Nearest', 'price': 'Compare listed prices'}


def _first_option(mode, result):
    cards = result.get('results', [])
    sort = result.get('sort') or {}
    prices = sort.get('price_comparison') or {}
    option = dict(mode=mode, label=ORDERS[mode], facility_id=None, name=None, tier=None,
                  distance_km=None, citation=None, price_citation=None, flags=[], price_basis=prices.get('ranked_by'),
                  comparable_quotes=prices.get('comparable_quotes'), safety_pinned=bool(prices.get('safety_pinned')), reason=sort.get('no_ranked_reason') or '')
    if result.get('error') or (result.get('review') or {}).get('passed') is False:
        option['reason'] = 'Comparison unavailable for this order.'
        return option
    if not cards:
        return option
    card = cards[0]
    option.update({key: card[key] for key in ('facility_id', 'name', 'tier', 'distance_km', 'flags')})
    evidence = next(iter(card.get('evidence', [])), None)
    if evidence:
        option['citation'] = dict(field=evidence['field'], quote=evidence.get('verbatim') or evidence['quote'],
                                  facility_id=evidence.get('source_facility_id') or card['facility_id'], source_urls=card.get('source_urls', []))
    if mode == 'price':
        option['reason'] = prices.get('note') or option['reason']
        price = card.get('price_info')
        if price:
            option['price_citation'] = {key: price[key] for key in ('field', 'quote')}
    return option


def compare_strategies(index, service, place, active_result, max_extra_km=25):
    """Return the first choice for each standard order. Preferences on the active card stay separate."""
    active_mode = active_result.get('sort_mode', 'default')
    standard = not (active_result.get('preferences') or {}).get('applied')
    options = []
    for mode in ORDERS:
        if mode == active_mode and standard:
            result = active_result
        else:
            result = recommend(index, service, place, sort_mode=mode, **({'max_extra_km': max_extra_km} if mode == 'price' else {}))
        options.append(_first_option(mode, result))

    evidence, nearest, price = options
    changed = bool(evidence['facility_id'] and nearest['facility_id'] and evidence['facility_id'] != nearest['facility_id'])
    difference = None
    if changed:
        difference = round(evidence['distance_km'] - nearest['distance_km'], 1)
        if difference:
            relation = 'closer to' if difference > 0 else 'farther from'
            movement = f"{abs(difference):g} km {relation} the search centre"
        else:
            movement = 'at the same displayed distance'
        summary = (f"{nearest['name']} is {movement} by straight line. "
                   f"The records give {nearest['tier'].title()} evidence there and {evidence['tier'].title()} evidence at {evidence['name']}.")
    elif evidence['facility_id'] and nearest['facility_id']:
        summary = f"{evidence['name']} comes first for both evidence and distance."
    elif any(o['facility_id'] for o in options):
        summary = 'The orders differ on whether a branch can be ranked. Check the branch and location notes.'
    else:
        summary = 'None of these orders returned a first choice for this search.'
    if price['facility_id']:
        if price['safety_pinned']:
            summary += ' The urgent-care rule keeps the closest eligible option without a conflicting service claim first when available.'
        elif price['price_basis'] == 'distance':
            summary += ' Price comparison falls back to distance.'
        elif price['price_basis'] == 'price' and price['facility_id'] != nearest['facility_id']:
            summary += f" Comparing documented prices puts {price['name']} first."
        elif price['price_basis'] not in ('price', 'distance') and price['reason']:
            summary += ' ' + price['reason']
    origin = active_result.get('origin') or {}
    precision = origin.get('precision_km')
    if difference and precision and origin.get('kind') != 'coordinates' and abs(difference) <= 2 * precision:
        summary += f" The starting point is approximate (about {precision:g} km). Your closest option may differ."
    return dict(summary=summary, options=options, top_changed=changed, straight_line_difference_km=difference)
