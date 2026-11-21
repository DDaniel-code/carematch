"""Build eval/review.html: one page with everything a person needs to judge each top-1 answer.

Shows the rows where the two model reviewers disagree (plus a few random agreements as a spot check), each with the
query, the full recommendation card, every quoted claim, data-quality warnings, and both model opinions.
Usage: python -m scripts.make_review_page [--spot 4]
"""
import argparse
import csv
import html
import random

from carematch.recommend import CareIndex, recommend

CSS = """
:root{--bg:#fafaf9;--card:#fff;--ink:#1c1917;--mute:#57534e;--line:#e7e5e4;--warn:#b45309;--ok:#15803d;--accent:#1d4ed8}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--card:#292524;--ink:#f5f5f4;--mute:#a8a29e;--line:#44403c;--warn:#f59e0b;--ok:#4ade80;--accent:#93c5fd}}
body{background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif;margin:0;padding:16px}
main{max-width:860px;margin:auto}.row{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
h1{font-size:22px}h2{font-size:17px;margin:0 0 4px}.mute{color:var(--mute)}blockquote{margin:6px 0;padding:4px 10px;border-left:3px solid var(--accent)}
.warn{color:var(--warn)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:640px){.grid{grid-template-columns:1fr}}
.op{border:1px solid var(--line);border-radius:8px;padding:8px}.tag{font-weight:600}.ask{background:var(--bg);border-radius:8px;padding:8px;margin-top:8px}
"""


def card_html(c):
    out = [f"<p><b>{html.escape(c['name'])}</b> — {c['distance_km']} km · <b>{c['tier']}</b> evidence · "
           f"{html.escape(c.get('type') or '')} · {html.escape(c.get('city') or '')}, {html.escape(c.get('state') or '')}</p>",
           f"<p class=mute>Why this tier: {html.escape('; '.join(c['tier_reasons']))}</p>"]
    for e in c['evidence']:
        out.append(f"<blockquote>“{html.escape(e['quote'])}” <span class=mute>— {e['field']}</span></blockquote>")
    for u in c['uncertainties']:
        out.append(f"<p class=warn>⚠ {html.escape(u)}</p>")
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spot', type=int, default=4)
    args = ap.parse_args()
    rows = list(csv.DictReader(open('eval/review_sheet.csv', encoding='utf-8')))
    queries = {q['id']: q for q in csv.DictReader(open('eval/queries.csv', encoding='utf-8'))}
    todo = [r for r in rows if r.get('models_agree') == 'no']
    agree = [r for r in rows if r.get('models_agree') == 'yes']
    spot = random.Random(11).sample(agree, min(args.spot, len(agree)))
    index = CareIndex.from_csv()
    parts = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
             f"<title>CareMatch review</title><style>{CSS}</style><main><h1>CareMatch: human review</h1>"
             f"<p>{len(todo)} answers where the two model reviewers disagree, then {len(spot)} random agreements as a spot check. "
             "For each, decide two things and reply with the id: <b>does the quote support the service</b> (yes / partly / no) and "
             "<b>is it one real facility</b> (yes / merged / duplicate). The page already shows everything from the record.</p>"]
    for label, group in (('Disagreements', todo), ('Spot check (models agree)', spot)):
        parts.append(f'<h1>{label}</h1>')
        for r in group:
            q = queries[r['id']]
            res = recommend(index, q['service'], q['place'])
            top = res['results'][0] if res['results'] else None
            parts.append(f"<section class=row><h2>{r['id']} · {html.escape(res['service_label'])} near "
                         f"{html.escape(res['origin']['label'])}</h2><p class=mute>{html.escape(q['scenario'])} · "
                         f"evidence can show: {html.escape(res.get('service_scope', ''))}</p>")
            if top:
                parts.append(card_html(top))
            parts.append("<div class=grid>")
            for who, pre in (('Claude (engine author)', 'model'), ('ChatGPT (independent)', 'xcheck')):
                parts.append(f"<div class=op><span class=tag>{who}</span><br>quote supports: <b>{html.escape(r[pre + '_quote_supports'])}</b>"
                             f" · one facility: <b>{html.escape(r[pre + '_one_facility'])}</b><br>"
                             f"<span class=mute>{html.escape(r[pre + '_note'])}</span></div>")
            parts.append("</div></section>")
    parts.append('</main>')
    with open('eval/review.html', 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(parts))
    print(f'wrote eval/review.html ({len(todo)} disagreements, {len(spot)} spot checks)')


if __name__ == '__main__':
    main()
