# Screenshots

Captured from the app running on the supplied data (Streamlit 1.38, the version Databricks Apps runs), at 1440 px wide
and 2× resolution; the two phone screenshots are 390 px wide at 3×.

| File | What it shows |
| --- | --- |
| [`01_find_care_home.png`](01_find_care_home.png) | **Find care**, before a search: one service, one place, one button. |
| [`02_results_dialysis_delhi.png`](02_results_dialysis_delhi.png) | Dialysis near Delhi. Each card quotes the sentence in the record that supports it, with its evidence tier, distance, and buttons to call, open the website and get directions; the numbered pins on the map match the list. The line above the cards compares the evidence-first order with the nearest option (1.6 km closer, weaker evidence). |
| [`03_evidence_details.png`](03_evidence_details.png) | The same search with the first card opened: the questions to ask on the phone, other routes, and what the records say. |
| [`04_did_you_mean.png`](04_did_you_mean.png) | "Banglore" is not found, so the page offers Bengaluru and Mangaluru as buttons. |
| [`05_call_plan_most_pins.png`](05_call_plan_most_pins.png) | **Verification map**, three calls, counting every PIN area equally: 365 more PIN areas within 50 km of a documented C-section facility if the three branches confirm. All three calls go to southern states. |
| [`06_call_plan_low_caesarean.png`](06_call_plan_low_caesarean.png) | The same budget, counting only PIN areas in districts with an NFHS-5 caesarean rate below 10%: the first call goes to Darbhanga Medical College and three calls reach 86 such PIN areas; the plan above reaches none of them. |
| [`07_mobile_home.png`](07_mobile_home.png) | **Find care** on a phone. |
| [`08_mobile_result.png`](08_mobile_result.png) | A result card on a phone: the call button is the full width of the card. |

The charts from the notebook are in [`../img/`](../img/).
