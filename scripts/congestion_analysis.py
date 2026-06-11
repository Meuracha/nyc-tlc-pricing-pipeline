"""
Congestion Pricing Impact Analysis
NYC Congestion Relief Zone Toll started January 5, 2025
Maps to JD: "Impact Tracking" + "Monitor Performance"
"""
import sys
sys.path.insert(0, '.')
from scripts.athena_connect import query as athena_query, GLUE_DB
import pandas as pd
import numpy as np
from scipy import stats
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


# ── 1. Overall monthly impact 2024 vs 2025 ───────────────────────────────────
print("=" * 60)
print("1. OVERALL IMPACT: 2024 vs 2025 (same months Jan–Dec)")
print("=" * 60)

overall = athena_query(f"""
    WITH y2024 AS (
        SELECT
            month(pickup_time)              AS month,
            COUNT(*)                        AS trips_2024,
            SUM(fare_amount)                AS rev_2024,
            AVG(fare_amount)                AS fare_2024,
            AVG(congestion_fee)             AS congestion_fee
        FROM {T}
        WHERE year = 2024
        GROUP BY month(pickup_time)
    ),
    y2025 AS (
        SELECT
            month(pickup_time)              AS month,
            COUNT(*)                        AS trips_2025,
            SUM(fare_amount)                AS rev_2025,
            AVG(fare_amount)                AS fare_2025
        FROM {T}
        WHERE year = 2025
        GROUP BY month(pickup_time)
    )
    SELECT
        y2024.month,
        y2024.trips_2024,
        y2025.trips_2025,
        ROUND((y2025.trips_2025 - y2024.trips_2024) * 100.0
            / NULLIF(y2024.trips_2024, 0), 2)           AS trip_change_pct,
        ROUND(y2024.fare_2024, 2)                        AS avg_fare_2024,
        ROUND(y2025.fare_2025, 2)                        AS avg_fare_2025,
        ROUND(y2025.fare_2025 - y2024.fare_2024, 2)     AS fare_delta,
        ROUND(y2024.congestion_fee, 2)                   AS avg_congestion_fee
    FROM y2024
    JOIN y2025 ON y2024.month = y2025.month
    ORDER BY y2024.month
""")

print(overall.to_string(index=False))
export_csv(overall, "congestion_monthly.csv")


# ── 2. Pre vs post aggregate ──────────────────────────────────────────────────
print("\n" + "=" * 60)
print("2. PRE vs POST CONGESTION PRICING")
print("   Pre  = 2024 | Post = 2025")
print("=" * 60)

pre_post = athena_query(f"""
    SELECT
        is_congestion_era,
        COUNT(*)                        AS total_trips,
        ROUND(AVG(fare_amount), 2)      AS avg_fare,
        ROUND(AVG(fare_per_km), 2)      AS avg_fare_per_km,
        ROUND(AVG(trip_distance), 2)    AS avg_distance,
        ROUND(AVG(congestion_fee), 4)   AS avg_congestion_fee
    FROM {T}
    WHERE year IN (2024, 2025)
    GROUP BY is_congestion_era
    ORDER BY is_congestion_era
""")

pre_post["era"] = pre_post["is_congestion_era"].map({0: "Pre (2024)", 1: "Post (2025)"})
print(pre_post[["era", "total_trips", "avg_fare", "avg_fare_per_km",
                "avg_distance", "avg_congestion_fee"]].to_string(index=False))

# statistical test
pre_sample = athena_query(f"""
    SELECT fare_amount FROM {T}
    WHERE year = 2024
    ORDER BY rand()
    LIMIT 50000
""")["fare_amount"].values

post_sample = athena_query(f"""
    SELECT fare_amount FROM {T}
    WHERE year = 2025
    ORDER BY rand()
    LIMIT 50000
""")["fare_amount"].values

t_stat, p_value = stats.ttest_ind(pre_sample, post_sample, equal_var=False)
print(f"\nFare t-test (pre vs post congestion):")
print(f"  T-statistic : {t_stat:.4f}")
print(f"  P-value     : {p_value:.6f}")
print(f"  Significant : {'YES ✅' if p_value < 0.05 else 'NO ❌'}")
print(f"  Fare change : ${np.mean(post_sample) - np.mean(pre_sample):+.2f} avg")


# ── 3. Most impacted zones ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("3. MOST IMPACTED ZONES BY CONGESTION PRICING")
print("=" * 60)

impacted = athena_query(f"""
    WITH z2024 AS (
        SELECT pickup_zone,
               COUNT(*) / 12.0          AS avg_monthly_trips,
               AVG(fare_amount)         AS avg_fare,
               AVG(congestion_fee)      AS avg_congestion_fee
        FROM {T} WHERE year = 2024
        GROUP BY pickup_zone
        HAVING COUNT(*) >= 1200
    ),
    z2025 AS (
        SELECT pickup_zone,
               COUNT(*) / 12.0          AS avg_monthly_trips,
               AVG(fare_amount)         AS avg_fare
        FROM {T} WHERE year = 2025
        GROUP BY pickup_zone
    )
    SELECT
        z2024.pickup_zone,
        ROUND(z2024.avg_monthly_trips, 0)   AS avg_monthly_trips_2024,
        ROUND(z2025.avg_monthly_trips, 0)   AS avg_monthly_trips_2025,
        ROUND((z2025.avg_monthly_trips - z2024.avg_monthly_trips) * 100.0
            / NULLIF(z2024.avg_monthly_trips, 0), 2) AS avg_trip_change_pct,
        ROUND(z2024.avg_fare, 2)            AS avg_fare_2024,
        ROUND(z2025.avg_fare, 2)            AS avg_fare_2025,
        ROUND(z2025.avg_fare - z2024.avg_fare, 2) AS avg_fare_delta,
        ROUND(z2024.avg_congestion_fee, 2)  AS avg_congestion_fee
    FROM z2024
    JOIN z2025 ON z2024.pickup_zone = z2025.pickup_zone
    ORDER BY avg_trip_change_pct ASC
    LIMIT 20
""")

print("Zones with largest demand DROP:")
print(impacted.to_string(index=False))
export_csv(impacted, "congestion_impacted_zones.csv")

benefited = athena_query(f"""
    WITH z2024 AS (
        SELECT pickup_zone,
               COUNT(*) / 12.0      AS avg_monthly_trips
        FROM {T} WHERE year = 2024
        GROUP BY pickup_zone
        HAVING COUNT(*) >= 1200
    ),
    z2025 AS (
        SELECT pickup_zone,
               COUNT(*) / 12.0      AS avg_monthly_trips,
               AVG(fare_amount)     AS avg_fare_2025
        FROM {T} WHERE year = 2025
        GROUP BY pickup_zone
    )
    SELECT
        z2024.pickup_zone,
        ROUND(z2024.avg_monthly_trips, 0)   AS avg_monthly_trips_2024,
        ROUND(z2025.avg_monthly_trips, 0)   AS avg_monthly_trips_2025,
        ROUND((z2025.avg_monthly_trips - z2024.avg_monthly_trips) * 100.0
            / NULLIF(z2024.avg_monthly_trips, 0), 2) AS avg_trip_change_pct,
        ROUND(z2025.avg_fare_2025, 2)       AS avg_fare_2025
    FROM z2024
    JOIN z2025 ON z2024.pickup_zone = z2025.pickup_zone
    ORDER BY avg_trip_change_pct DESC
    LIMIT 10
""")

print("\nZones with largest demand GAIN:")
print(benefited.to_string(index=False))
export_csv(benefited, "congestion_benefited_zones.csv")


# ── 4. Business recommendation ────────────────────────────────────────────────
print("\n" + "=" * 60)
print("4. BUSINESS RECOMMENDATION")
print("=" * 60)

total_2024 = overall["trips_2024"].sum()
total_2025 = overall["trips_2025"].sum()
agg_trip_change = (total_2025 - total_2024) / total_2024 * 100
agg_fare_delta  = overall["avg_fare_2025"].mean() - overall["avg_fare_2024"].mean()

print(f"Total trips 2024           : {total_2024:,.0f}")
print(f"Total trips 2025           : {total_2025:,.0f}")
print(f"Aggregate demand change    : {agg_trip_change:+.2f}%")
print(f"Avg fare change            : ${agg_fare_delta:+.2f}")
print()

if agg_trip_change < -5:
    print("→ Congestion pricing caused significant demand reduction.")
    print("  Adjust surge thresholds down in Manhattan CBD zones.")
elif agg_trip_change < 0:
    print("→ Mild demand reduction post-congestion pricing.")
    print("  Monitor monthly — if trend continues, revisit fee structure.")
else:
    print("→ Demand stable despite congestion pricing.")
    print("  Inelastic demand — room for modest fee optimization.")

print("\n✅ Congestion analysis complete.")