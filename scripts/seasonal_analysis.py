"""
Seasonal Analysis — Q1/Q2/Q3/Q4 patterns per zone
Uses 2022-2025 for richer seasonal patterns
Maps to JD: "Demand-Supply Analysis" + "Monitor Performance"
"""
import sys
sys.path.insert(0, '.')
from scripts.athena_connect import query as athena_query, GLUE_DB
import pandas as pd
import boto3 as _boto3
import io as _io

_s3     = _boto3.client("s3", region_name="ap-southeast-1")
_BUCKET = "nyc-tlc-pricing-588738598819-ap-southeast-1-an"

def export_csv(df, filename):
    buf = _io.StringIO()
    df.to_csv(buf, index=False)
    _s3.put_object(Bucket=_BUCKET, Key=f"export/{filename}",
                   Body=buf.getvalue().encode("utf-8"), ContentType="text/csv")
    print(f"  → s3://{_BUCKET}/export/{filename}")

T = f"{GLUE_DB}.silver_yellow"


# ── 1. Seasonal index by quarter (2022-2025 avg) ──────────────────────────────
print("=" * 60)
print("1. SEASONAL INDEX BY QUARTER (2022–2025 average)")
print("=" * 60)

seasonal_q = athena_query(f"""
    WITH quarterly AS (
        SELECT
            year,
            quarter(pickup_time)            AS quarter,
            pickup_zone,
            COUNT(*)                        AS trip_count,
            AVG(fare_amount)                AS avg_fare
        FROM {T}
        WHERE year IN (2022, 2023, 2024, 2025)
        GROUP BY year, quarter(pickup_time), pickup_zone
    ),
    with_index AS (
        SELECT
            year, quarter, pickup_zone, trip_count, avg_fare,
            trip_count * 1.0 / AVG(trip_count) OVER (
                PARTITION BY year, pickup_zone
            )                               AS seasonal_index
        FROM quarterly
    )
    SELECT
        quarter,
        SUM(trip_count)                     AS total_trips,
        ROUND(AVG(avg_fare), 2)             AS avg_fare,
        ROUND(AVG(seasonal_index), 3)       AS avg_seasonal_index,
        COUNT(DISTINCT pickup_zone)         AS zones
    FROM with_index
    GROUP BY quarter
    ORDER BY quarter
""")

print(seasonal_q.to_string(index=False))
print("\nSeasonal index > 1.0 = above annual average")
export_csv(seasonal_q, "seasonal_by_quarter.csv")


# ── 2. Most seasonal zones (2022-2025) ────────────────────────────────────────
print("\n" + "=" * 60)
print("2. MOST SEASONAL ZONES (2022–2025 average)")
print("=" * 60)

seasonal_zones = athena_query(f"""
    WITH quarterly AS (
        SELECT
            pickup_zone,
            quarter(pickup_time)            AS quarter,
            COUNT(*)                        AS trip_count,
            AVG(fare_amount)                AS avg_fare
        FROM {T}
        WHERE year IN (2022, 2023, 2024, 2025)
        GROUP BY pickup_zone, quarter(pickup_time)
    ),
    with_index AS (
        SELECT
            pickup_zone, quarter, trip_count, avg_fare,
            trip_count * 1.0 / AVG(trip_count) OVER (
                PARTITION BY pickup_zone
            )                               AS seasonal_index
        FROM quarterly
    )
    SELECT
        pickup_zone,
        ROUND(MAX(seasonal_index) - MIN(seasonal_index), 3) AS seasonal_range,
        ROUND(MAX(seasonal_index), 3)   AS peak_index,
        ROUND(MIN(seasonal_index), 3)   AS trough_index,
        ROUND(AVG(avg_fare), 2)         AS avg_fare,
        SUM(trip_count)                 AS total_trips
    FROM with_index
    GROUP BY pickup_zone
    HAVING SUM(trip_count) >= 4000
    ORDER BY seasonal_range DESC
    LIMIT 20
""")

print(seasonal_zones.to_string(index=False))
export_csv(seasonal_zones, "seasonal_zones.csv")


# ── 3. Q1 vs Q3 — winter vs summer (2022-2025 avg) ───────────────────────────
print("\n" + "=" * 60)
print("3. WINTER vs SUMMER — Q1 vs Q3 (2022–2025 average)")
print("=" * 60)

q1_vs_q3 = athena_query(f"""
    WITH q1 AS (
        SELECT pickup_zone,
               COUNT(*)            AS trips_q1,
               AVG(fare_amount)    AS fare_q1
        FROM {T}
        WHERE year IN (2022, 2023, 2024, 2025)
          AND quarter(pickup_time) = 1
        GROUP BY pickup_zone
    ),
    q3 AS (
        SELECT pickup_zone,
               COUNT(*)            AS trips_q3,
               AVG(fare_amount)    AS fare_q3
        FROM {T}
        WHERE year IN (2022, 2023, 2024, 2025)
          AND quarter(pickup_time) = 3
        GROUP BY pickup_zone
    )
    SELECT
        q1.pickup_zone,
        q1.trips_q1,
        q3.trips_q3,
        ROUND((q3.trips_q3 - q1.trips_q1) * 100.0
            / NULLIF(q1.trips_q1, 0), 2)    AS summer_vs_winter_pct,
        ROUND(q1.fare_q1, 2)                 AS fare_q1,
        ROUND(q3.fare_q3, 2)                 AS fare_q3
    FROM q1
    JOIN q3 ON q1.pickup_zone = q3.pickup_zone
    WHERE q1.trips_q1 >= 2000
    ORDER BY ABS(summer_vs_winter_pct) DESC
    LIMIT 20
""")

print(q1_vs_q3.to_string(index=False))
export_csv(q1_vs_q3, "seasonal_q1_vs_q3.csv")


# ── 4. Time bucket by quarter (2022-2025) ─────────────────────────────────────
print("\n" + "=" * 60)
print("4. TIME BUCKET BY QUARTER (2022–2025)")
print("=" * 60)

bucket_seasonal = athena_query(f"""
    WITH base AS (
        SELECT
            year,
            quarter(pickup_time)    AS quarter,
            time_bucket,
            COUNT(*)                AS trip_count,
            AVG(fare_amount)        AS avg_fare
        FROM {T}
        WHERE year IN (2022, 2023, 2024, 2025)
        GROUP BY year, quarter(pickup_time), time_bucket
    ),
    with_index AS (
        SELECT
            year, quarter, time_bucket, trip_count, avg_fare,
            trip_count * 1.0 / AVG(trip_count) OVER (
                PARTITION BY year
            )                       AS seasonal_index
        FROM base
    )
    SELECT
        year,
        quarter,
        time_bucket,
        SUM(trip_count)             AS total_trips,
        ROUND(AVG(avg_fare), 2)     AS avg_fare,
        ROUND(AVG(seasonal_index), 3) AS seasonal_index
    FROM with_index
    GROUP BY year, quarter, time_bucket
    ORDER BY year, quarter, time_bucket
""")

print(bucket_seasonal.to_string(index=False))
export_csv(bucket_seasonal, "seasonal_time_bucket.csv")

print("\n✅ Seasonal analysis complete.")