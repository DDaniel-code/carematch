# Describe-the-situation input: need lexicon contract (for the app)

Code: [`carematch/needs.py`](../carematch/needs.py) · tests: `tests/test_needs.py` · eval: `python -m scripts.run_needs_eval`.
Pure function, standard library, no index needed (instant). It does **not** change `recommend()`.

## Call

```python
from carematch.needs import interpret_need
x = interpret_need("delivery ke baad khoon bahut beh raha hai")
```

## Result

| Key | Type | Use in the UI |
| --- | --- | --- |
| `status` | `'matched'` · `'ambiguous'` · `'no_match'` | `no_match`: keep the Medical service select empty, show `understood_as`. `ambiguous`: prefill but require the user to confirm. |
| `service` | service key or `None` | prefill the **Medical service** select (`SERVICES[key]['label']`) |
| `service_label` | str | label for that service |
| `urgency` | `'time_critical'` · `'default'` · `'can_travel'` · `None` | lexicon label for evaluation; the worker selects the travel preference |
| `red_flag` | bool | when true, show `call_now` **first**, above everything else |
| `call_now` | str or `None` | "108 (ambulance); 102 for pregnant women and newborns in most states" |
| `matched` | list of `{condition, condition_id, phrase, service}` | `phrase` is a verbatim substring of the user's text: show "From your words '…'" |
| `also_possible` | list of service keys | offer as quick switches |
| `understood_as` | str | one-line explanation to display |
| `notes` | list of str | condition-specific advice (e.g. "ask about a cath lab", "ask whether anti-snake venom is available") |
| `disclaimer` | str | always show: not a diagnosis, user can change service and urgency |
| `input` | str | cleaned input |

Suggested flow: optional text box "Describe the situation" above the Medical service select → on change, call
`interpret_need`, suggest a service, show the matched words, `call_now` (if any) and the disclaimer → the user can
edit both before **Search for care**. Never search automatically on an `ambiguous` result.

## Lexicon (13 condition groups, English + romanized Hindi)

| Condition | Service | Urgency | Red flag |
| --- | --- | --- | --- |
| prolonged / obstructed labour | C-section | time-critical | yes |
| heavy bleeding in pregnancy or after delivery (needs pregnancy context) | C-section | time-critical | yes |
| fits / eclampsia in pregnancy | C-section | time-critical | yes |
| newborn in distress / born too early / low birth weight | NICU | time-critical | yes |
| road accident / head injury | Trauma (also CT) | time-critical | yes |
| broken bone | Trauma | default | no |
| burns / scalds | Burn care | time-critical | yes |
| chest pain / heart attack | Emergency care (note: ask about a cath lab) | time-critical | yes |
| suspected stroke | Emergency care (also CT) | time-critical | yes |
| snake bite / poisoning | Emergency care (note: anti-snake venom) | time-critical | yes |
| kidney failure / dialysis | Dialysis | can travel | no (note: missed session + breathless = 108) |
| heart surgery advised | Cardiac surgery | default | no |
| MRI / CT advised | MRI / CT scan | default | no |

Rules: English negation ("no bleeding") is ignored, but not across "but/and/;" ("no bleeding but labour for 20 hours"
still matches labour). Several conditions → most severe first, others in `also_possible`; two red-flag conditions with
different services → `ambiguous`. Imaging words lose to a specific condition ("head injury needs CT" → Trauma).
"heartburn", "sunburn", "fever and cough" → `no_match`.

## Evaluation

52 team-written phrases (39 English, 13 Hindi), including 6 that must not match and 1 ambiguous: status, service,
urgency and red flag all correct (52/52). These phrases were written by the team, so this measures lexicon coverage,
not accuracy on real user input. Romanized Hindi spelling varies; the Hindi entries should be checked by a Hindi speaker.
