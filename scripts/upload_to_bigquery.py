"""
Upload CSV exports from S3 to BigQuery
S3 export/ → BigQuery tlc_analytics dataset
Uses load_table_from_file (reliable) 
Special handling: monthly_trend gets ds column added
forecast_full_series: adds Dec 2025 actual to forecast series for line continuity
"""
import boto3
import io
import pandas as pd
from google.cloud import bigquery

S3_BUCKET  = "nyc-tlc-pricing-588738598819-ap-southeast-1-an"
S3_PREFIX  = "export/"
BQ_PROJECT = "nyc-tlc-pricing"
BQ_DATASET = "tlc_analytics"
REGION     = "ap-southeast-1"

s3 = boto3.client("s3", region_name=REGION)
bq = bigquery.Client(project=BQ_PROJECT)

FILES = {
    "kpi_summary.csv":               "kpi_summary",
    "zone_performance.csv":          "zone_performance",
    "peak_hours.csv":                "peak_hours",
    "supply_gap.csv":                "supply_gap",
    "elasticity.csv":                "elasticity",
    "monthly_trend.csv":             "monthly_trend",
    "yoy_summary.csv":               "yoy_summary",
    "yoy_q1_comparison.csv":         "yoy_q1_comparison",
    "yoy_top_growing_zones.csv":     "yoy_top_growing_zones",
    "yoy_declining_zones.csv":       "yoy_declining_zones",
    "seasonal_by_quarter.csv":       "seasonal_by_quarter",
    "seasonal_zones.csv":            "seasonal_zones",
    "seasonal_q1_vs_q3.csv":         "seasonal_q1_vs_q3",
    "seasonal_time_bucket.csv":      "seasonal_time_bucket",
    "congestion_monthly.csv":        "congestion_monthly",
    "congestion_impacted_zones.csv": "congestion_impacted_zones",
    "congestion_benefited_zones.csv":"congestion_benefited_zones",
    "did_summary.csv":               "did_summary",
    "ab_test_result.csv":            "ab_test_result",
    "ab_test_by_tier.csv":           "ab_test_by_tier",
    "forecast_2026.csv":             "forecast_2026",
    "forecast_full_series.csv":      "forecast_full_series",
    "fhv_wait_time.csv":             "fhv_wait_time",
}

def transform_forecast_full_series(df):
    df["ds"] = pd.to_datetime(df["ds"])
    # Add Dec 2025 actual row into forecast series for line chart continuity
    dec_2025 = df[
        (df["ds"].astype(str).str.startswith("2025-12")) &
        (df["type"] == "actual")
    ].copy()
    dec_2025["type"] = "forecast"
    df = pd.concat([df, dec_2025]).sort_values(["type", "ds"]).reset_index(drop=True)
    print(f"    forecast series starts: {df[df['type']=='forecast']['ds'].min()}")
    return df

# Tables that need special transformation before upload
TRANSFORMS = {
    "monthly_trend": lambda df: df.assign(
        ds=pd.to_datetime(df[["year", "month"]].assign(day=1))
    ),
    "congestion_monthly": lambda df: df.assign(
        ds=pd.to_datetime(df["month"].apply(lambda m: f"2024-{m:02d}-01"))
    ),
    "ab_test_by_tier": lambda df: df.assign(
        result=df["significant"].apply(lambda x: "✅ pass" if x else "✗ fail")
    ).drop(columns=["significant"]),
    "forecast_full_series": transform_forecast_full_series,
    "forecast_2026": lambda df: df.assign(
        ds=pd.to_datetime(df["ds"])
    ),
}

job_config = bigquery.LoadJobConfig(
    autodetect=True,
    write_disposition="WRITE_TRUNCATE",
    source_format=bigquery.SourceFormat.CSV,
    skip_leading_rows=1,
)

print(f"Uploading {len(FILES)} files to BigQuery...")
print(f"Project : {BQ_PROJECT}")
print(f"Dataset : {BQ_DATASET}")
print()

success = 0
failed  = 0

for csv_file, table_name in FILES.items():
    s3_key   = f"{S3_PREFIX}{csv_file}"
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{table_name}"

    try:
        obj  = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
        data = obj["Body"].read()

        if table_name in TRANSFORMS:
            df   = pd.read_csv(io.BytesIO(data))
            df   = TRANSFORMS[table_name](df)
            data = df.to_csv(index=False).encode()

        job = bq.load_table_from_file(
            io.BytesIO(data),
            table_id,
            job_config=job_config
        )
        job.result()

        table_ref = bq.get_table(table_id)
        print(f"  ✅ {table_name:<35} ({table_ref.num_rows:,} rows)")
        success += 1

    except Exception as e:
        print(f"  ❌ {table_name:<35} {e}")
        failed += 1

print(f"\n✅ Done: {success} uploaded, {failed} failed")