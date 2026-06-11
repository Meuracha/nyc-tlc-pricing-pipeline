"""
Transform: verify Glue tables and create Athena views
Silver layer views covering 2022-2026
"""
import sys
sys.path.insert(0, ".")
from scripts.athena_connect import query as athena_query, execute, GLUE_DB
import time

print("Verifying Glue tables via Athena...")

# ── 1. Check row counts ───────────────────────────────────────────────────────
print("\nRow counts:")

checks = [
    ("yellow_trips", f"SELECT COUNT(*) AS total FROM {GLUE_DB}.yellow_trips"),
    ("fhv_trips",    f"SELECT COUNT(*) AS total FROM {GLUE_DB}.fhv_trips"),
]

for label, sql in checks:
    try:
        df = athena_query(sql)
        print(f"  {label:<20}: {int(df.iloc[0,0]):>12,}")
    except Exception as e:
        print(f"  {label:<20}: ❌ {e}")


# ── 2. Create Athena views ────────────────────────────────────────────────────
print("\nCreating Athena mart views...")

mart_views = {
    "silver_yellow": f"""
        CREATE OR REPLACE VIEW {GLUE_DB}.silver_yellow AS
        SELECT
            tpep_pickup_datetime                            AS pickup_time,
            year(tpep_pickup_datetime)                      AS year,
            month(tpep_pickup_datetime)                     AS month,
            hour(tpep_pickup_datetime)                      AS pickup_hour,
            quarter(tpep_pickup_datetime)                   AS quarter,
            CASE
                WHEN hour(tpep_pickup_datetime) BETWEEN 7  AND 9  THEN 'morning_rush'
                WHEN hour(tpep_pickup_datetime) BETWEEN 17 AND 19 THEN 'evening_rush'
                WHEN hour(tpep_pickup_datetime) BETWEEN 0  AND 5  THEN 'late_night'
                ELSE 'off_peak'
            END                                             AS time_bucket,
            CASE WHEN tpep_pickup_datetime >= TIMESTAMP '2025-01-05 00:00:00'
                 THEN 1 ELSE 0 END                          AS is_congestion_era,
            pulocationid                                    AS pickup_zone,
            dolocationid                                    AS dropoff_zone,
            fare_amount,
            trip_distance,
            fare_amount / NULLIF(trip_distance, 0)          AS fare_per_km,
            COALESCE(CAST(congestion_surcharge AS DOUBLE), 0) AS congestion_fee
        FROM {GLUE_DB}.yellow_trips
        WHERE fare_amount     BETWEEN 2.5 AND 500
          AND trip_distance   BETWEEN 0.1 AND 100
          AND CAST(passenger_count AS INTEGER) BETWEEN 1 AND 6
          AND tpep_pickup_datetime >= TIMESTAMP '2022-01-01 00:00:00'
          AND tpep_pickup_datetime  < TIMESTAMP '2026-04-01 00:00:00'
          AND tpep_dropoff_datetime > tpep_pickup_datetime
    """,

    "silver_fhv": f"""
        CREATE OR REPLACE VIEW {GLUE_DB}.silver_fhv AS
        SELECT
            pickup_datetime                                 AS pickup_time,
            year(pickup_datetime)                           AS year,
            month(pickup_datetime)                          AS month,
            hour(pickup_datetime)                           AS pickup_hour,
            quarter(pickup_datetime)                        AS quarter,
            CASE
                WHEN hour(pickup_datetime) BETWEEN 7  AND 9  THEN 'morning_rush'
                WHEN hour(pickup_datetime) BETWEEN 17 AND 19 THEN 'evening_rush'
                WHEN hour(pickup_datetime) BETWEEN 0  AND 5  THEN 'late_night'
                ELSE 'off_peak'
            END                                             AS time_bucket,
            CASE WHEN pickup_datetime >= TIMESTAMP '2025-01-05 00:00:00'
                 THEN 1 ELSE 0 END                          AS is_congestion_era,
            pulocationid                                    AS pickup_zone,
            dolocationid                                    AS dropoff_zone,
            base_passenger_fare                             AS fare_amount,
            trip_miles                                      AS trip_distance,
            base_passenger_fare / NULLIF(trip_miles, 0)     AS fare_per_km,
            COALESCE(CAST(congestion_surcharge AS DOUBLE), 0) AS congestion_fee,
            date_diff('minute', request_datetime, pickup_datetime) AS wait_time_minutes,
            CASE hvfhs_license_num
                WHEN 'HV0003' THEN 'Uber'
                WHEN 'HV0005' THEN 'Lyft'
                ELSE 'Other'
            END                                             AS platform
        FROM {GLUE_DB}.fhv_trips
        WHERE base_passenger_fare  BETWEEN 2.5 AND 500
          AND trip_miles           BETWEEN 0.1 AND 100
          AND pickup_datetime      >= TIMESTAMP '2022-01-01 00:00:00'
          AND pickup_datetime       < TIMESTAMP '2026-04-01 00:00:00'
          AND dropoff_datetime      > pickup_datetime
          AND date_diff('minute', request_datetime, pickup_datetime) BETWEEN 0 AND 60
    """,
}

for name, sql in mart_views.items():
    try:
        execute(sql)
        print(f"  ✅ {name}")
    except Exception as e:
        print(f"  ❌ {name}: {e}")

print("\nTransform complete.")
print(f"Views: {GLUE_DB}.silver_yellow, {GLUE_DB}.silver_fhv")
print(f"Year range: 2022–2026 Q1")