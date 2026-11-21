"""Load the source tables from wherever they are, as rows the engine understands.

Sources, in the order `load()` tries them:
  spark      - a Databricks notebook (`spark` passed in)
  warehouse  - a Databricks App: SQL warehouse attached as an app resource (env DATABRICKS_WAREHOUSE_ID)
  volume     - snapshot CSVs written by notebooks/00_export_data.py to /Volumes/workspace/carematch/exports
  local      - data/*.csv on a laptop (or CAREMATCH_DATA_DIR)

The engine was calibrated on the CSV export, so every value is converted to the text that export contains:
None/NaN -> '', numbers -> str(number). Rows are dicts keyed by the source column names.
"""
import csv
import io
import math
import os
import sys
import time

SOURCE_SCHEMA = 'databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset'
FACILITIES_SQL = f'SELECT * FROM {SOURCE_SCHEMA}.facilities'
# One row per PIN x district x state; identical to notebooks/00_export_data.py.
PINCODES_SQL = f"""
SELECT pincode, TRIM(district) AS district, TRIM(statename) AS statename,
       COUNT(*) AS n_offices,
       COUNT(TRY_CAST(latitude AS DOUBLE)) AS n_geocoded,
       AVG(TRY_CAST(latitude AS DOUBLE))  AS lat,
       AVG(TRY_CAST(longitude AS DOUBLE)) AS lon,
       MIN(TRY_CAST(latitude AS DOUBLE))  AS lat_min, MAX(TRY_CAST(latitude AS DOUBLE))  AS lat_max,
       MIN(TRY_CAST(longitude AS DOUBLE)) AS lon_min, MAX(TRY_CAST(longitude AS DOUBLE)) AS lon_max
FROM {SOURCE_SCHEMA}.india_post_pincode_directory
GROUP BY pincode, TRIM(district), TRIM(statename)
"""
EXPORT_DIR = '/Volumes/workspace/carematch/exports'
FILES = ('facilities.csv', 'pincodes.csv')


def cell(value):
    """A source value as the CSV export writes it."""
    if value is None:
        return ''
    if isinstance(value, float):
        return '' if math.isnan(value) else str(value)
    return str(value)


def to_rows(columns, records):
    return [{c: cell(v) for c, v in zip(columns, rec)} for rec in records]


def _read_csv(text_or_file):
    csv.field_size_limit(sys.maxsize)
    fh = io.StringIO(text_or_file) if isinstance(text_or_file, str) else text_or_file
    return list(csv.DictReader(fh))


# ---- individual sources ----------------------------------------------------------------------------------------

def load_local(directory=None):
    directory = directory or os.environ.get('CAREMATCH_DATA_DIR') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    out = []
    for name in FILES:
        with open(os.path.join(directory, name), newline='', encoding='utf-8') as fh:
            out.append(_read_csv(fh))
    return out[0], out[1]


def load_spark(spark):
    def query(sql_text):
        df = spark.sql(sql_text)
        return to_rows(df.columns, df.collect())
    return query(FACILITIES_SQL), query(PINCODES_SQL)


def load_warehouse(warehouse_id=None):
    """Read through a SQL warehouse with the app's own credentials (Databricks Apps inject them)."""
    from databricks import sql
    from databricks.sdk.core import Config

    warehouse_id = warehouse_id or os.environ.get('DATABRICKS_WAREHOUSE_ID')
    if not warehouse_id:
        raise RuntimeError('DATABRICKS_WAREHOUSE_ID is not set (attach a SQL warehouse resource to the app)')
    cfg = Config()
    host = cfg.host.replace('https://', '').rstrip('/')
    with sql.connect(server_hostname=host, http_path=f'/sql/1.0/warehouses/{warehouse_id}',
                     credentials_provider=lambda: cfg.authenticate) as conn:
        def query(sql_text):
            with conn.cursor() as cur:
                cur.execute(sql_text)
                return to_rows([d[0] for d in cur.description], cur.fetchall())
        return query(FACILITIES_SQL), query(PINCODES_SQL)


def load_volume(directory=EXPORT_DIR):
    """Snapshot CSVs in a Unity Catalog Volume: a plain path in notebooks, the Files API in apps."""
    if os.path.isdir(directory):
        return load_local(directory)
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    out = []
    for name in FILES:
        data = w.files.download(f'{directory}/{name}').contents.read()
        out.append(_read_csv(data.decode('utf-8')))
    return out[0], out[1]


# ---- entry point -----------------------------------------------------------------------------------------------

def load(spark=None, order=None):
    """Return (facility_rows, pincode_rows, info). Tries sources in order; info says which one worked and why others failed."""
    if order is None:
        if spark is not None:
            order = ['spark', 'volume']
        elif os.environ.get('DATABRICKS_APP_NAME') or os.environ.get('DATABRICKS_WAREHOUSE_ID'):
            order = ['warehouse', 'volume']
        else:
            order = ['local']
    loaders = {'spark': lambda: load_spark(spark), 'warehouse': load_warehouse, 'volume': load_volume, 'local': load_local}
    errors = []
    for name in order:
        started = time.perf_counter()
        try:
            facilities, pincodes = loaders[name]()
        except Exception as exc:  # report every failed source, then try the next one
            errors.append(f'{name}: {type(exc).__name__}: {exc}')
            continue
        info = {'source': name, 'facility_rows': len(facilities), 'pincode_rows': len(pincodes),
                'load_seconds': round(time.perf_counter() - started, 1), 'failed_sources': errors}
        return facilities, pincodes, info
    raise RuntimeError('Could not load the source tables. ' + ' | '.join(errors))
