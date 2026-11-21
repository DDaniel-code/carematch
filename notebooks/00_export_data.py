# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Export source tables to a Volume (for local development)
# MAGIC Writes full CSVs of the three challenge tables to `/Volumes/workspace/carematch/exports/`.
# MAGIC Download them from **Catalog → workspace → carematch → exports**. Read-only on the source tables.

# COMMAND ----------

SRC = "databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset"
OUT = "/Volumes/workspace/carematch/exports"

spark.sql("CREATE SCHEMA IF NOT EXISTS workspace.carematch")
spark.sql("CREATE VOLUME IF NOT EXISTS workspace.carematch.exports")

# COMMAND ----------

facilities = spark.table(f"{SRC}.facilities").toPandas()
facilities.to_csv(f"{OUT}/facilities.csv", index=False)

pincodes = spark.sql(f"""
SELECT pincode, TRIM(district) AS district, TRIM(statename) AS statename,
       COUNT(*) AS n_offices,
       COUNT(TRY_CAST(latitude AS DOUBLE)) AS n_geocoded,
       AVG(TRY_CAST(latitude AS DOUBLE))  AS lat,
       AVG(TRY_CAST(longitude AS DOUBLE)) AS lon,
       MIN(TRY_CAST(latitude AS DOUBLE))  AS lat_min, MAX(TRY_CAST(latitude AS DOUBLE))  AS lat_max,
       MIN(TRY_CAST(longitude AS DOUBLE)) AS lon_min, MAX(TRY_CAST(longitude AS DOUBLE)) AS lon_max
FROM {SRC}.india_post_pincode_directory
GROUP BY pincode, TRIM(district), TRIM(statename)
""").toPandas()
pincodes.to_csv(f"{OUT}/pincodes.csv", index=False)

nfhs = spark.table(f"{SRC}.nfhs_5_district_health_indicators").toPandas()
nfhs.to_csv(f"{OUT}/nfhs5.csv", index=False)

print({"facilities": len(facilities), "pincodes": len(pincodes), "nfhs5": len(nfhs)})
# Expected: facilities 10088, pincodes ~20k, nfhs5 706
