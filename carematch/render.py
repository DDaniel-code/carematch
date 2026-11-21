"""Plain-text rendering of a recommendation result (CLI and notebook)."""

TIER_WORD = {'strong': 'STRONG evidence', 'moderate': 'MODERATE evidence', 'weak': 'WEAK evidence'}


def _card_text(c, header):
    lines = [header]
    dist = f"{c['distance_km']} km" if c['distance_km'] is not None else 'distance unknown'
    meta = ', '.join(x for x in (c['type'], c['operator'], f"{c['beds']} beds" if c['beds'] else None) if x)
    lines.append(f"   {dist} · {TIER_WORD.get(c['tier'], c['tier'])} · {meta}")
    lines.append(f"   {c['address'] or c['city']}{', PIN ' + c['pin'] if c['pin'] else ''}")
    lines.append(f"   Why: {'; '.join(c['tier_reasons'])}")
    for e in c['evidence']:
        lines.append(f"     “{e['quote'][:160]}”  [{e['field']}]")
    if c.get('why_ranked'):
        lines.append(f"   Order: {c['why_ranked']}")
    for u in c['uncertainties']:
        lines.append(f"   ! {u}")
    if c['distance_basis'] and c['distance_basis'] != 'facility coordinates':
        lines.append(f"   ! distance measured from {c['distance_basis']}")
    lines.append(f"   Call: {c['phone'] or 'no phone listed'}" + (f" · {c['website']}" if c['website'] else ''))
    lines.append(f"   Ask: {c['ask_when_calling'][0]}")
    if c.get('note'):
        lines.append(f"   Note: {c['note']}")
    return '\n'.join(lines)


def to_text(result):
    if 'error' in result:
        return 'Error: ' + result['error']
    o = result['origin']
    out = [f"{result['service_label']} near {o['label']}  (location precision ~{o['precision_km']} km)"]
    out += [f"  note: {n}" for n in o['notes']]
    if result.get('service_scope'):
        out.append(f"  what the evidence can show: {result['service_scope']}")
    if result.get('action_advice'):
        out.append(f"What to do: {result['action_advice']}")
    if result['results']:
        out.append(f"Searched up to {result['band_km']} km.")
        for c in result['results']:
            out.append(_card_text(c, f"\n{c['rank']}. {c['name']}"))
    else:
        out.append(f"\nNo facility with credible evidence within {300} km.")
    if result['farther_stronger']:
        out.append(_card_text(result['farther_stronger'], f"\n+ {result['farther_stronger']['name']}"))
    if result['nearest_beyond']:
        out.append(_card_text(result['nearest_beyond'], f"\n> {result['nearest_beyond']['name']}"))
    for c in result['weak_nearby']:
        out.append(_card_text(c, f"\n? (weak, unverified) {c['name']}"))
    b = result['considered']['by_band']
    out.append('\nConsidered: ' + '; '.join(f"≤{k} km: {v['strong']} strong / {v['moderate']} moderate / {v['weak']} weak"
                                            for k, v in b.items()))
    out.append(result['disclaimer'])
    return '\n'.join(out)
