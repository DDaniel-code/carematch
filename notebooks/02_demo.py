# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · CareMatch demo (notebook version of the app)
# MAGIC Pick a service and type a place in the widgets at the top, then run the last cell.
# MAGIC Same engine as the Databricks App (`carematch` package in this repo), reading the source tables directly.
# MAGIC Backup for the live demo if the app is unavailable.

# COMMAND ----------

import os
import sys

# The notebook runs from notebooks/; make the repo root importable.
sys.path.insert(0, os.path.abspath('..'))

from carematch import datasource
from carematch.recommend import CareIndex, recommend
from carematch.render import to_text
from carematch.services import SERVICES

# COMMAND ----------

facilities, pincodes, info = datasource.load(spark=spark)
index = CareIndex(facilities, pincodes)
print(info)

# COMMAND ----------

labels = [spec['label'] for spec in SERVICES.values()]
dbutils.widgets.dropdown('service', labels[0], labels, '1. Service')
dbutils.widgets.text('place', 'Patna', '2. Place (city, district, PIN, or "lat, lon")')

# COMMAND ----------

result = recommend(index, dbutils.widgets.get('service'), dbutils.widgets.get('place'))
print(to_text(result))
