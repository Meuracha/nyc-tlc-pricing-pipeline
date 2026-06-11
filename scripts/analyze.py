"""
Demand-Supply & Price Elasticity Analysis
Maps to JD: "Demand-Supply Analysis" + "Data Extraction & Reporting"
Queries directly from Athena silver_yellow (no mart views needed)
"""
import sys
sys.path.insert(0, '.')
from scripts.athena_connect import query as athena_query, GLUE_DB
import pandas as pd
import numpy as np
import boto3 as _boto3
import io as _io

_s3     = _boto3.client("s3", region_name="ap-southeast-1")
_BUCKET = "nyc-tlc-pricing-588738598819-ap-southeast-1-an"

def export_csv(df, filename: str):
    buf = _io.StringIO()
    df.to_csv(buf, index=False)
    _s3.put_object(
        Bucket=_BUCKET,
        Key=f"export/{filename}",
        Body=buf.getvalue().encode("utf-8"),
        ContentType="text/csv"
    )
    print(f"  → s3://{_BUCKET}/export/{filename}")

T = f"{GLUE_DB}.silver_yellow"


# ── 1. Zone performance summary ──────────────────────────────────────────────
print("=" * 55)
print("1. ZONE PERFORMANCE SUMMARY")
print("=" * 55)

zone_perf = athena_query(f"""
    SELECT
        pickup_zone,
        COUNT(*)                                AS total_trips,
        ROUND(AVG(fare_amount), 2)              AS avg_fare,
        ROUND(AVG(fare_per_km), 2)              AS avg_fare_per_km,
        COUNT(*) * 1.0 / AVG(COUNT(*)) OVER ()  AS demand_index_vs_avg
    FROM {T}
    WHERE year IN (2024, 2025, 2026)
    GROUP BY pickup_zone
    ORDER BY total_trips DESC
    LIMIT 20
""")

print(zone_perf.to_string(index=False))
export_csv(zone_perf, "zone_performance.csv")


# ── 2. Peak hour detection ────────────────────────────────────────────────────
print("\n" + "=" * 55)
print("2. PEAK HOUR DETECTION (top 10 zones)")
print("=" * 55)

peak_hours = athena_query(f"""
    WITH top_zones AS (
        SELECT pickup_zone
        FROM {T}
        WHERE year IN (2024, 2025, 2026)
        GROUP BY pickup_zone
        ORDER BY COUNT(*) DESC
        LIMIT 10
    )
    SELECT
        s.pickup_zone,
        s.pickup_hour,
        s.time_bucket,
        COUNT(*)                AS trip_count,
        ROUND(AVG(s.fare_amount), 2) AS avg_fare,
        COUNT(*) * 1.0 / AVG(COUNT(*)) OVER (
            PARTITION BY s.pickup_zone
        )                       AS demand_index
    FROM {T} s
    INNER JOIN top_zones t ON s.pickup_zone = t.pickup_zone
    WHERE s.year IN (2024, 2025, 2026)
    GROUP BY s.pickup_zone, s.pickup_hour, s.time_bucket
    ORDER BY s.pickup_zone, s.pickup_hour
""")

print(peak_hours.head(30).to_string(index=False))
export_csv(peak_hours, "peak_hours.csv")


# ── 3. Supply gap index ───────────────────────────────────────────────────────
print("\n" + "=" * 55)
print("3. SUPPLY GAP INDEX")
print("=" * 55)

supply_gap = athena_query(f"""
    WITH base AS (
        SELECT
            pickup_zone,
            time_bucket,
            COUNT(*)                        AS trip_count,
            ROUND(AVG(fare_amount), 2)      AS avg_fare,
            ROUND(STDDEV(fare_amount), 2)   AS fare_volatility
        FROM {T}
        WHERE year IN (2024, 2025, 2026)
        GROUP BY pickup_zone, time_bucket
    ),
    with_index AS (
        SELECT
            pickup_zone,
            time_bucket,
            trip_count,
            avg_fare,
            fare_volatility,
            ROUND(trip_count * 1.0 / AVG(trip_count) OVER (
                PARTITION BY pickup_zone
            ), 3)                           AS demand_index
        FROM base
    )
    SELECT
        pickup_zone,
        time_bucket,
        demand_index,
        avg_fare,
        fare_volatility,
        trip_count                          AS total_trips,
        ROUND(demand_index * fare_volatility, 3) AS supply_gap_score
    FROM with_index
    WHERE demand_index > 1.2
    ORDER BY supply_gap_score DESC
    LIMIT 20
""")

print(supply_gap.to_string(index=False))
export_csv(supply_gap, "supply_gap.csv")


# ── 4. Price elasticity ───────────────────────────────────────────────────────
print("\n" + "=" * 55)
print("4. PRICE ELASTICITY — FARE vs DEMAND")
print("=" * 55)

elasticity = athena_query(f"""
    WITH fare_buckets AS (
        SELECT
            pickup_zone,
            time_bucket,
            FLOOR(fare_amount / 5) * 5  AS fare_bucket,
            COUNT(*)                    AS trip_count,
            AVG(fare_amount)            AS avg_fare,
            AVG(trip_distance)          AS avg_distance
        FROM {T}
        WHERE year IN (2024, 2025, 2026)
        GROUP BY pickup_zone, time_bucket, FLOOR(fare_amount / 5) * 5
        HAVING COUNT(*) >= 30
    )
    SELECT
        pickup_zone,
        time_bucket,
        fare_bucket,
        trip_count,
        ROUND(avg_fare, 2)          AS avg_fare,
        ROUND(avg_distance, 2)      AS avg_distance,
        ROUND(
            (trip_count - LAG(trip_count) OVER (
                PARTITION BY pickup_zone, time_bucket
                ORDER BY fare_bucket
            )) * 100.0 / NULLIF(LAG(trip_count) OVER (
                PARTITION BY pickup_zone, time_bucket
                ORDER BY fare_bucket
            ), 0), 2
        )                           AS pct_demand_change
    FROM fare_buckets
    ORDER BY pickup_zone, time_bucket, fare_bucket
""")

print(elasticity.head(30).to_string(index=False))
export_csv(elasticity, "elasticity.csv")


# ── 5. KPI summary ────────────────────────────────────────────────────────────
print("\n" + "=" * 55)
print("5. KPI SUMMARY")
print("=" * 55)

kpi = athena_query(f"""
    SELECT
        COUNT(DISTINCT pickup_zone)     AS total_zones,
        COUNT(*)                        AS total_trips,
        ROUND(AVG(fare_amount), 2)      AS overall_avg_fare,
        ROUND(AVG(fare_per_km), 2)      AS overall_fare_per_km,
        ROUND(MIN(fare_amount), 2)      AS min_fare,
        ROUND(MAX(fare_amount), 2)      AS max_fare
    FROM {T}
    WHERE year IN (2024, 2025, 2026)
""")

print(kpi.to_string(index=False))
export_csv(kpi, "kpi_summary.csv")


# ── 6. Pattern stability check ────────────────────────────────────────────────
print("\n" + "=" * 55)
print("6. PATTERN STABILITY CHECK (Jan vs Feb vs Mar 2024)")
print("=" * 55)

monthly = athena_query(f"""
    SELECT
        month(pickup_time)      AS month,
        pickup_zone,
        AVG(fare_amount)        AS avg_fare,
        AVG(fare_per_km)        AS avg_fare_per_km,
        COUNT(*)                AS trip_count
    FROM {T}
    WHERE year = 2024
      AND month(pickup_time) BETWEEN 1 AND 6
    GROUP BY month(pickup_time), pickup_zone
    HAVING COUNT(*) >= 100
""")

def month_series(m, col="avg_fare"):
    return monthly[monthly["month"] == m].set_index("pickup_zone")[col]

jan_fare  = month_series(1)
feb_fare  = month_series(2)
mar_fare  = month_series(3)
jan_trips = month_series(1, "trip_count")
feb_trips = month_series(2, "trip_count")
mar_trips = month_series(3, "trip_count")

common = jan_fare.index.intersection(feb_fare.index).intersection(mar_fare.index)

print(f"\nZones with data in all 3 months: {len(common)}")
print("\n── Avg fare correlation ──")
print(f"  Jan vs Feb : {jan_fare[common].corr(feb_fare[common]):.4f}")
print(f"  Feb vs Mar : {feb_fare[common].corr(mar_fare[common]):.4f}")
print(f"  Jan vs Mar : {jan_fare[common].corr(mar_fare[common]):.4f}")

print("\n── Trip volume correlation ──")
print(f"  Jan vs Feb : {jan_trips[common].corr(feb_trips[common]):.4f}")
print(f"  Feb vs Mar : {feb_trips[common].corr(mar_trips[common]):.4f}")
print(f"  Jan vs Mar : {jan_trips[common].corr(mar_trips[common]):.4f}")

fare_stable = all(
    jan_fare[common].corr(x[common]) > 0.95
    for x in [feb_fare, mar_fare]
)
trip_stable = all(
    jan_trips[common].corr(x[common]) > 0.95
    for x in [feb_trips, mar_trips]
)

print(f"\n  Fare stable  : {'YES ✅' if fare_stable else 'NO ❌'}")
print(f"  Volume stable: {'YES ✅' if trip_stable else 'NO ❌'}")

# Q1 vs Q2
print(f"\n── Q1 vs Q2 comparison ──")
for m_num, label in [(4, "Apr"), (5, "May"), (6, "Jun")]:
    m_fare  = month_series(m_num)
    m_trips = month_series(m_num, "trip_count")
    cq      = jan_fare.index.intersection(m_fare.index)
    if len(cq) > 0:
        print(f"  Jan vs {label} — fare r: {jan_fare[cq].corr(m_fare[cq]):.4f}  "
              f"| volume r: {jan_trips[cq].corr(m_trips[cq]):.4f}")

export_csv(monthly, "monthly_stability.csv")

print("\n✅ Analysis complete. All exports uploaded to S3")