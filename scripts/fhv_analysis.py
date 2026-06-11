"""
FHV (Uber/Lyft) Wait Time Analysis
Calculates actual driver supply gap using request → pickup wait time
Key advantage over Yellow Taxi: has request_datetime → wait_time_minutes
HV0003=Uber, HV0005=Lyft
"""
import sys
sys.path.insert(0, '.')
from scripts.athena_connect import query as athena_query, GLUE_DB
import boto3
import io

s3 = boto3.client("s3", region_name="ap-southeast-1")
BUCKET = "nyc-tlc-pricing-588738598819-ap-southeast-1-an"
T = f"{GLUE_DB}.silver_fhv"

print("=" * 55)
print("FHV WAIT TIME ANALYSIS — DRIVER SUPPLY GAP")
print("=" * 55)

df = athena_query(f"""
    SELECT
        year,
        pickup_zone,
        time_bucket,
        platform,
        COUNT(*)                                            AS total_trips,
        ROUND(AVG(wait_time_minutes), 2)                    AS avg_wait_min,
        ROUND(approx_percentile(wait_time_minutes, 0.5), 2) AS median_wait_min,
        ROUND(approx_percentile(wait_time_minutes, 0.9), 2) AS p90_wait_min,
        CASE
            WHEN AVG(wait_time_minutes) > 10 THEN 'incentive'
            WHEN AVG(wait_time_minutes) > 7  THEN 'monitor'
            ELSE 'ok'
        END AS action
    FROM {T}
    WHERE year BETWEEN 2022 AND 2026
      AND wait_time_minutes BETWEEN 1 AND 60
    GROUP BY year, pickup_zone, time_bucket, platform
    HAVING COUNT(*) >= 100
    ORDER BY avg_wait_min DESC
""")

print(f"Rows: {len(df)}")
print(df.head(10).to_string())

print("\n── Year comparison (avg wait by year) ──")
print(df.groupby("year")["avg_wait_min"].mean().round(2).to_string())

print("\n── Platform comparison (avg wait by platform) ──")
print(df.groupby("platform")["avg_wait_min"].mean().round(2).to_string())

buf = io.StringIO()
df.to_csv(buf, index=False)
s3.put_object(
    Bucket=BUCKET,
    Key="export/fhv_wait_time.csv",
    Body=buf.getvalue().encode("utf-8"),
    ContentType="text/csv"
)
print("\n✅ Done — exported to s3://export/fhv_wait_time.csv")