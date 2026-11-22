# C-section travel scenarios

Open **Travel time scenarios** in the Streamlit sidebar. Choose a time budget,
departure delay and middle speed. Inspect a six-digit PIN to see the selected
branch, distance, service tier and exact facility text.

The reference dataset contains 14,008 reliable PIN centres. The snapshot keeps
the closest eligible Strong branch and closest eligible Moderate branch for each
PIN. Eligibility requires a service quote and a usable position. Whole-record
mixing flags and service-specific foreign claims exclude a branch. For each
remaining branch, the model uses the maximum straight-line distance across its
plausible positions. Postal areas without a reliable centre are omitted.

For distance d, a trip takes delay + 60 × d × road multiplier / speed in minutes.
The nine equiprobable, hypothetical conditions combine three speeds (middle
speed ±10 km/h and the middle itself) with road multipliers 1.2, 1.4 and 1.6.
The arrival probability under this discrete distribution is the fraction within
the budget. Travel times, ferry connections and hospital acceptance were not
observed. These calculations support planning sensitivity analysis.

The optional service-availability sliders are user assumptions. Within each
tier, arrival probability falls monotonically with distance, so its closest
eligible branch attains the tier maximum. Assuming independent trip conditions
and on-site service availability, the map selects the largest product of arrival
probability and assumed availability across the two branches. Ties prefer a
shorter trip. Clinical outcomes require additional data.

Rebuild from the repository root with `python -m scripts.travel_snapshot`
(NumPy required for the offline rebuild). Deploy both `analysis/travel_*.csv`
files with the app. The interactive page performs no warehouse read.
