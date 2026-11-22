# Deploying CareMatch on Databricks Free Edition

Two entry points, same engine: the **Databricks App** (for users) and **`notebooks/02_demo.py`** (reproduction and backup demo).
Menu names below may differ slightly between workspace versions.

## 0. Get the code into the workspace

Workspace → your Git folder for `DDaniel-code/carematch` → branch `main` → **Pull**.
Check that `app.yaml`, `requirements.txt`, `app/app.py` and `carematch/datasource.py` are there.

## 1. Notebook (do this first: it proves the code runs on the real tables)

Open `notebooks/02_demo.py`, attach serverless compute, **Run all**. The second cell prints something like
`{'source': 'spark', 'facility_rows': 10088, 'pincode_rows': 21162, ...}`. Change the widgets at the top
(service, place) and rerun the last cell.

## 2. Create the app

1. **Compute → Apps → Create app → Create a custom app**. Name: `carematch`.
2. **Add resource → SQL warehouse**: pick the workspace's serverless warehouse, permission **Can use**,
   resource key **`sql-warehouse`** (must match `app.yaml`).
3. Create, then **Deploy** with source code path = the Git folder root (the folder that contains `app.yaml`),
   e.g. `/Workspace/Users/<you>/carematch`.

## 3. Let the app read the data

The app runs as its own service principal (shown on the app's page, named after the app). Grant it read access:

- **Preferred**: Catalog Explorer → catalog `databricks_virtue_foundation_dataset_dais_2026` → **Permissions → Grant** →
  the app's service principal → `USE CATALOG`, `USE SCHEMA`, `SELECT`.
- **If you cannot grant on that catalog**: run `notebooks/00_export_data.py` once (writes CSV snapshots to
  `/Volumes/workspace/carematch/exports`), then grant the service principal `USE CATALOG` on `workspace` and
  `USE SCHEMA` + `READ VOLUME` on `workspace.carematch`. The app falls back to the snapshot automatically.

## 4. Check it

Open the app URL. The first visit loads the facility and location index. The first search for each service prepares shared evidence for that service. Subsequent searches reuse it.
The sidebar says where the data came from:

- `Source: warehouse · 10,088 facilities …`: reading Unity Catalog directly.
- `Source: volume …` plus `Fallback used; failed: warehouse: …`: snapshot in use; the failure text says what permission is missing.
- An error page "Could not load the facility data": no source worked; the message lists each failure. **App page → Logs** has details.

Try: Dialysis / `Patna`; MRI scan / `Darbhanga`; Burn care / `Gaya`; Dialysis / `Aurangabad` (shows the "Use Aurangabad, Bihar" button).

## 5. Before judging

Free Edition stops an app **24 hours after its last start or deploy**. On the morning of the deadline: Pull, **Deploy** again,
open the URL once to warm it up, and run the four example searches.

## Local development

```bash
python -m unittest discover -s tests -v
streamlit run app/app.py        # reads data/*.csv
```
