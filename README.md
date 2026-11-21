# CareMatch

Find the right care in India: give a service and a location, get up to three facilities with quoted evidence,
an evidence tier, distance, and what still needs to be confirmed by phone.

Built on Databricks Free Edition with the Virtue Foundation facility dataset (CMU × Databricks Datathon, Nov 2026).

- Design and ranking rules: [docs/design.md](docs/design.md)
- Data profile: [docs/data_profile.md](docs/data_profile.md)

## Local development

Python 3.10+, standard library only for the core package.

```bash
python -m unittest discover -s tests -v
python -m scripts.ask "dialysis|Sitamarhi" "emergency C-section|Aurangabad, Bihar" "NICU|845401"
python -m scripts.calibrate_evidence          # tier counts + review samples on the full data
```

```python
from carematch.recommend import CareIndex, recommend
from carematch.render import to_text
index = CareIndex.from_csv('data/facilities.csv', 'data/pincodes.csv')
print(to_text(recommend(index, 'dialysis', '800001')))
```

Raw data exports go in `data/` (git-ignored); the dataset is not committed.

## Credits

Parsing helpers in `carematch/textutil.py` are adapted from Charlie's search MVP (`Sa1kyo121/carematch-india`, branch `feature/search`).
