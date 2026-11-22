"""Automatic quality review run on every recommendation result.

Each check is deterministic and is shown to the user in the app ("Quality checks: 7/7 passed").
The most important one is citation fidelity: every quoted sentence must appear verbatim in the named
column of that facility's source record, so the system can never show a claim the data does not contain.
"""
import re

from .evidence import TIERS
from .price import comparison_key
from .textutil import fragments, normalize, text


def _quote_in_record(index, card, ev):
    for i in index.by_id.get(text(card['facility_id']), []):
        raw = index.rows[i].get(ev['field'])
        if ev['field'] == 'description':
            if ev['verbatim'] and ev['verbatim'] in text(raw):
                return True
        elif ev['verbatim'] in fragments(raw):
            return True
    return False


def _check(name, passed, detail=''):
    return {'name': name, 'passed': bool(passed), 'detail': '' if passed else detail}


def review(index, result):
    results = result.get('results', [])
    extras = [c for c in (result.get('farther_stronger'), result.get('nearest_beyond')) if c] + result.get('weak_nearby', [])
    extras += result.get('cost_unknown_options', [])
    prefs_on = (result.get('preferences') or {}).get('applied', False)
    every = results + extras + result.get('runner_ups', [])
    checks = []

    bad_tier = [c['name'] for c in results if c['tier'] not in ('strong', 'moderate')]
    checks.append(_check('At most 3 recommendations, all with Strong or Moderate evidence',
                         len(results) <= 3 and not bad_tier, f'{len(results)} results; weak/none: {bad_tier}'))

    keys = [re.sub(r'[^a-z0-9]+', ' ', normalize(c['name'])).strip() for c in results]
    checks.append(_check('No facility listed twice', len(keys) == len(set(keys)),
                         'duplicate names: ' + ', '.join(sorted({k for k in keys if keys.count(k) > 1}))))

    missing = [(c['name'], e['field'], e['quote'][:60]) for c in every for e in c['evidence']
               if not _quote_in_record(index, c, e)]
    n_quotes = sum(len(c['evidence']) for c in every)
    checks.append(_check(f'Every quote appears word for word in the facility record ({n_quotes} quotes)',
                         not missing, f'not found: {missing[:3]}'))

    no_quote = [c['name'] for c in results if not c['evidence']]
    checks.append(_check('Every recommendation cites at least one quote', not no_quote, f'no quote: {no_quote}'))

    bad_dist = [c['name'] for c in every if c['distance_km'] is not None and c['distance_km'] <= 0]
    checks.append(_check('Distances are positive or explicitly unknown (never a fake 0 km)', not bad_dist,
                         f'bad distance: {bad_dist}'))

    band = result.get('band_km')
    inside = all(c['distance_km'] is not None and band is not None
                 and c['distance_km'] <= max(band, c.get('found_within_km') or band) + 0.05 for c in results)
    sort_mode = result.get('sort_mode', 'default')
    sort = result.get('sort') or {}
    if sort_mode in ('nearest', 'price'):
        bad_rank = [c['name'] for c in results
                    if c['location_confidence'] == 'low' or 'possible_merged_record' in c['flags']]
        abstained_ok = bool(results) or bool(sort.get('no_ranked_reason')) or not sort
        checks.append(_check(f'{sort_mode.capitalize()} mode: only branch-resolved options with a certain location are ranked; '
                             'if none qualifies, nothing is ranked and the reason is given',
                             not bad_rank and abstained_ok, f'unresolved but ranked: {bad_rank}'))
    if sort_mode == 'nearest':
        d = [c['distance_km'] for c in results]
        moved = [c for c in results if c.get('safety_reordered')]
        ordered = all(a <= b + 0.05 for a, b in zip(d[len(moved):], d[len(moved) + 1:]))
        checks.append(_check('Nearest mode: ordered by straight-line distance among branch-resolved options with a certain location',
                             ordered and inside, f'distances={d}'))
    elif sort_mode == 'price':
        pc = sort.get('price_comparison', {})
        rest = [c for c in results if not c.get('safety_pinned')]
        pinned_ok = all(not c.get('safety_pinned') or i == 0 for i, c in enumerate(results))
        if pc.get('ranked_by') == 'price':
            hi = [c['price_info']['amount_max_inr'] if c['price_info']['amount_max_inr'] is not None else float('inf')
                  for c in rest if c.get('price_comparable')]
            keys = {comparison_key(c['price_info']) for c in rest if c.get('price_comparable')}
            ordered = all(a <= b for a, b in zip(hi, hi[1:])) and len(keys) <= 1 and \
                all(k[0] != 'unspecified' for k in keys)
        else:
            d = [c['distance_km'] for c in rest]
            ordered = all(a <= b + 0.05 for a, b in zip(d, d[1:]))
        budget = pc.get('budget_km')
        in_budget = all(budget is not None and c['distance_km'] <= budget + 0.05 for c in results)
        honest = not pc.get('cheapest_claim') or pc.get('comparable_quotes', 0) >= 2
        checks.append(_check('Price mode: only like-for-like documented prices (same unit and conditions) are ranked, within '
                             'the extra-distance budget; urgent services keep the nearest safe option first; no "cheapest" claim '
                             'from fewer than two comparable quotes', ordered and in_budget and honest and pinned_ok,
                             f"ranked_by={pc.get('ranked_by')}, in_budget={in_budget}, cheapest_claim={pc.get('cheapest_claim')}"))
    elif prefs_on:
        scores = [c['preference']['score'] for c in results]
        ordered = all(a >= b for a, b in zip(scores, scores[1:]))
        checks.append(_check('Ordered by preference score (highest first); all within the search radius',
                             ordered and inside, f'scores={scores}, inside={inside}'))
        bad = []
        for c in results + result.get('runner_ups', []) + result.get('cost_unknown_options', []):
            rows = [index.rows[i] for i in index.by_id.get(text(c['facility_id']), [])]
            cites = [(x.get('field'), x.get('quote')) for x in c['preference']['components'] if x.get('quote')]
            cites += [(s['field'], s['quote']) for x in c['preference']['components'] for s in x.get('signals', [])]
            for field, quote in cites:
                ok = any((text(r.get(field)) == quote) if field == 'operatorTypeId'
                         else (quote in fragments(r.get(field)) or (field == 'description' and quote in text(r.get(field))))
                         for r in rows)
                if not ok:
                    bad.append((c['name'], field, quote[:50]))
        checks.append(_check('Every preference reason that cites the record quotes it word for word', not bad,
                             f'not found: {bad[:3]}'))
    else:
        # nearest search radius first; inside one radius, tier then distance
        keyseq = [(c.get('found_within_km', band) or 0, TIERS.index(c['tier']),
                   c['distance_km'] if c['distance_km'] is not None else float('inf')) for c in results]
        ordered = all(a[0] < b[0] or (a[0] == b[0] and (a[1] < b[1] or (a[1] == b[1] and a[2] <= b[2] + 0.05)))
                      for a, b in zip(keyseq, keyseq[1:]))
        checks.append(_check('Ordered nearest search radius first, then evidence tier, then distance; all within the radius',
                             ordered and inside, f'order ok={ordered}, inside {band} km={inside}'))

    priced = [c for c in every + [x for key in ('branch_unresolved', 'location_uncertain', 'price_unknown_nearby',
                                                 'price_not_comparable') for x in sort.get(key, [])]
              if c.get('price_info') or c.get('price_context')]
    bad_price = []
    for c in priced:
        rows = [index.rows[i] for i in index.by_id.get(text(c['facility_id']), [])]
        quotes = ([c['price_info']] if c.get('price_info') else []) + list(c.get('price_context') or [])
        for q in quotes:
            if not any(q['quote'] in fragments(r.get(q['field'])) for r in rows):
                bad_price.append((c['name'], q['field'], q['quote'][:50]))
    if priced:
        checks.append(_check('Every price quote appears word for word in the facility record', not bad_price,
                             f'not found: {bad_price[:3]}'))

    ranked_extra = [c['name'] for c in extras + result.get('runner_ups', []) if 'rank' in c]
    numbered = [c.get('rank') for c in results] == list(range(1, len(results) + 1))
    checks.append(_check('Only recommendations are numbered; extras and runner-ups are labelled, not ranked',
                         numbered and not ranked_extra, f'ranks={[c.get("rank") for c in results]}, ranked extras={ranked_extra}'))

    no_ask = [c['name'] for c in results if not c.get('ask_when_calling')]
    checks.append(_check('Every recommendation says what to confirm by phone, and the disclaimer is present',
                         not no_ask and bool(result.get('disclaimer')), f'missing questions: {no_ask}'))

    return {'passed': all(c['passed'] for c in checks), 'checks': checks}
