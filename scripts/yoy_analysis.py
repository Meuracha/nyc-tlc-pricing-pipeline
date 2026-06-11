"""
Year-over-Year Trend Analysis
Maps to JD: "Monitor Performance" + "Impact Tracking"

Part A: Full year YoY — 2022, 2023, 2024, 2025 (complete years only)
Part B: Q1 comparison — 2022-2026 (apples-to-apples)
Monthly trend — 2022-2026 (includes Q1 2026 for line chart)
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


# ══════════════════════════════════════════════════════════════
# PART A: Full Year YoY (2022-2025 only — complete years)
# ══════════════════════════════════════════════════════════════
print("=" * 60)
print("PART A: FULL YEAR YoY (2022–2025)")
print("=" * 60)

yoy_summary = athena_query(f"""
    SELECT
        year,
        COUNT(*)                        AS total_trips,
        ROUND(AVG(fare_amount), 2)      AS avg_fare,
        ROUND(AVG(fare_per_km), 2)      AS avg_fare_per_km,
        ROUND(SUM(fare_amount), 0)      AS total_revenue,
        COUNT(DISTINCT pickup_zone)     AS active_zones
    FROM {T}
    WHERE year IN (2022, 2023, 2024, 2025)
    GROUP BY year
    ORDER BY year
""")

print(yoy_summary.to_string(index=False))

# เพิ่ม growth columns
yoy_summary = yoy_summary.sort_values("year")
yoy_summary["trip_growth_pct"] = yoy_summary["total_trips"].pct_change() * 100
yoy_summary["fare_growth_pct"] = yoy_summary["avg_fare"].pct_change() * 100
yoy_summary["trip_growth_pct"] = yoy_summary["trip_growth_pct"].round(2)
yoy_summary["fare_growth_pct"] = yoy_summary["fare_growth_pct"].round(2)

for col in ["total_trips", "avg_fare", "total_revenue"]:
    vals  = yoy_summary[col].tolist()
    years = yoy_summary["year"].tolist()
    print(f"\n{col} growth:")
    for i in range(1, len(vals)):
        growth = (vals[i] - vals[i-1]) / vals[i-1] * 100
        print(f"  {years[i-1]} → {years[i]}: {growth:+.1f}%")

export_csv(yoy_summary, "yoy_summary.csv")


# ── Top growing zones 2024 → 2025 ────────────────────────────────────────────
print("\n" + "=" * 60)
print("TOP GROWING ZONES (2024 → 2025)")
print("=" * 60)

growing = athena_query(f"""
    WITH z2024 AS (
        SELECT pickup_zone,
               COUNT(*)            AS trips_2024,
               AVG(fare_amount)    AS fare_2024
        FROM {T} WHERE year = 2024
        GROUP BY pickup_zone
    ),
    z2025 AS (
        SELECT pickup_zone,
               COUNT(*)            AS trips_2025,
               AVG(fare_amount)    AS fare_2025
        FROM {T} WHERE year = 2025
        GROUP BY pickup_zone
    )
    SELECT
        z2024.pickup_zone,
        z2024.trips_2024,
        z2025.trips_2025,
        ROUND((z2025.trips_2025 - z2024.trips_2024) * 100.0
            / NULLIF(z2024.trips_2024, 0), 2)       AS trip_growth_pct,
        ROUND(z2024.fare_2024, 2)                    AS fare_2024,
        ROUND(z2025.fare_2025, 2)                    AS fare_2025,
        ROUND(z2025.fare_2025 - z2024.fare_2024, 2) AS fare_delta
    FROM z2024
    JOIN z2025 ON z2024.pickup_zone = z2025.pickup_zone
    WHERE z2024.trips_2024 >= 1000
    ORDER BY trip_growth_pct DESC
    LIMIT 15
""")

print(growing.to_string(index=False))
export_csv(growing, "yoy_top_growing_zones.csv")


# ── Top declining zones 2024 → 2025 ──────────────────────────────────────────
print("\n" + "=" * 60)
print("TOP DECLINING ZONES (2024 → 2025)")
print("=" * 60)

declining = athena_query(f"""
    WITH z2024 AS (
        SELECT pickup_zone, COUNT(*) AS trips_2024
        FROM {T} WHERE year = 2024 GROUP BY pickup_zone
    ),
    z2025 AS (
        SELECT pickup_zone, COUNT(*) AS trips_2025
        FROM {T} WHERE year = 2025 GROUP BY pickup_zone
    )
    SELECT
        z2024.pickup_zone,
        z2024.trips_2024,
        z2025.trips_2025,
        ROUND((z2025.trips_2025 - z2024.trips_2024) * 100.0
            / NULLIF(z2024.trips_2024, 0), 2) AS trip_growth_pct
    FROM z2024
    JOIN z2025 ON z2024.pickup_zone = z2025.pickup_zone
    WHERE z2024.trips_2024 >= 1000
    ORDER BY trip_growth_pct ASC
    LIMIT 15
""")

print(declining.to_string(index=False))
export_csv(declining, "yoy_declining_zones.csv")


# ── Monthly trend 2022-2026 (รวม 2026 Q1 สำหรับ line chart) ──────────────────
print("\n" + "=" * 60)
print("MONTHLY TREND 2022–2026")
print("=" * 60)

monthly_trend = athena_query(f"""
    SELECT
        year,
        month(pickup_time)              AS month,
        COUNT(*)                        AS total_trips,
        ROUND(AVG(fare_amount), 2)      AS avg_fare,
        ROUND(SUM(fare_amount), 0)      AS total_revenue
    FROM {T}
    WHERE year IN (2022, 2023, 2024, 2025, 2026)
    GROUP BY year, month(pickup_time)
    ORDER BY year, month(pickup_time)
""")

print(monthly_trend.to_string(index=False))

# เพิ่ม ds column สำหรับ Looker Studio
monthly_trend["ds"] = pd.to_datetime(
    monthly_trend[["year", "month"]].assign(day=1)
)
export_csv(monthly_trend, "monthly_trend.csv")


# ══════════════════════════════════════════════════════════════
# PART B: Q1 Comparison 2022–2026 (apples-to-apples)
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("PART B: Q1 COMPARISON 2022–2026 (Jan–Mar only)")
print("=" * 60)

q1_comparison = athena_query(f"""
    SELECT
        year,
        COUNT(*)                        AS q1_trips,
        ROUND(AVG(fare_amount), 2)      AS avg_fare,
        ROUND(SUM(fare_amount), 0)      AS q1_revenue,
        COUNT(DISTINCT pickup_zone)     AS active_zones
    FROM {T}
    WHERE year IN (2022, 2023, 2024, 2025, 2026)
      AND month(pickup_time) BETWEEN 1 AND 3
    GROUP BY year
    ORDER BY year
""")

print(q1_comparison.to_string(index=False))

# Q1 YoY growth
print(f"\nQ1 trip growth:")
vals  = q1_comparison["q1_trips"].tolist()
years = q1_comparison["year"].tolist()
for i in range(1, len(vals)):
    growth = (vals[i] - vals[i-1]) / vals[i-1] * 100
    print(f"  Q1 {years[i-1]} → Q1 {years[i]}: {growth:+.1f}%")

export_csv(q1_comparison, "yoy_q1_comparison.csv")


# ── 2026 Q1 snapshot ──────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("2026 Q1 SNAPSHOT vs 2025 Q1")
print("=" * 60)

q1_2025 = q1_comparison[q1_comparison["year"] == 2025]["q1_trips"].values[0]
q1_2026 = q1_comparison[q1_comparison["year"] == 2026]["q1_trips"].values[0]
q1_change = (q1_2026 - q1_2025) / q1_2025 * 100

print(f"Q1 2025 trips : {q1_2025:>10,.0f}")
print(f"Q1 2026 trips : {q1_2026:>10,.0f}")
print(f"YoY change    : {q1_change:>+10.2f}%")

if q1_change < -5:
    print("→ Significant Q1 demand decline — monitor closely")
elif q1_change < 0:
    print("→ Mild Q1 decline — consistent with 2024→2025 trend")
else:
    print("→ Q1 demand stable or growing")

print("\n✅ YoY analysis complete.")