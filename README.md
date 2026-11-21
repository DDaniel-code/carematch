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
```

Raw data exports go in `data/` (git-ignored); the dataset is not committed.

## Credits

Parsing helpers in `carematch/textutil.py` are adapted from Charlie's search MVP (`Sa1kyo121/carematch-india`, branch `feature/search`).
