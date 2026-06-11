"""
Demand Forecast 2026 using Prophet
Uses 2024-2025 monthly trip data to forecast Apr-Dec 2026
Maps to JD: "Monitor Performance" + business trend analysis
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

def export_csv(df, filename):
    buf = _io.StringIO()
    df.to_csv(buf, index=False)
    _s3.put_object(Bucket=_BUCKET, Key=f"export/{filename}",
                   Body=buf.getvalue().encode("utf-8"), ContentType="text/csv")
    print(f"  → s3://{_BUCKET}/export/{filename}")

T = f"{GLUE_DB}.silver_yellow"

try:
    from prophet import Prophet
except ImportError:
    import subprocess
    print("Installing prophet...")
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "prophet", "--quiet"])
    from prophet import Prophet

import warnings
warnings.filterwarnings("ignore")


# ── 1. Monthly time series ────────────────────────────────────────────────────
print("=" * 60)
print("DEMAND FORECAST 2026 — Prophet Model")
print("=" * 60)

monthly = athena_query(f"""
    SELECT
        date_trunc('month', pickup_time)    AS ds,
        COUNT(*)                            AS trip_count,
        AVG(fare_amount)                    AS avg_fare,
        SUM(fare_amount)                    AS total_revenue
    FROM {T}
    WHERE year IN (2022, 2023, 2024, 2025)
    GROUP BY date_trunc('month', pickup_time)
    ORDER BY date_trunc('month', pickup_time)
""")

monthly["ds"] = pd.to_datetime(monthly["ds"])
print(f"\nTraining data: {monthly['ds'].min().date()} → {monthly['ds'].max().date()}")
print(f"Months available: {len(monthly)}")
print(monthly[["ds", "trip_count", "avg_fare"]].to_string(index=False))


# ── 2. Prophet model — trip count ─────────────────────────────────────────────
print("\n── Fitting Prophet model (trip count)...")

df_prophet = monthly[["ds", "trip_count"]].rename(columns={"trip_count": "y"})
df_prophet["y"] = np.log(df_prophet["y"])

model = Prophet(
    yearly_seasonality=True,
    weekly_seasonality=False,
    daily_seasonality=False,
    seasonality_mode="multiplicative",
    interval_width=0.95,
    changepoint_prior_scale=0.3,
)
model.fit(df_prophet)

future   = model.make_future_dataframe(periods=9, freq="MS")
forecast = model.predict(future)

forecast["trips_forecast"] = np.exp(forecast["yhat"]).round(0)
forecast["trips_lower"]    = np.exp(forecast["yhat_lower"]).round(0)
forecast["trips_upper"]    = np.exp(forecast["yhat_upper"]).round(0)

actual_end   = monthly["ds"].max()
forecast_out = forecast[forecast["ds"] > actual_end][
    ["ds", "trips_forecast", "trips_lower", "trips_upper", "trend"]
].copy()
forecast_out["trend"] = np.exp(forecast_out["trend"]).round(0)

print(f"\nForecast Apr–Dec 2026:")
print(forecast_out.to_string(index=False))


# ── 3. Prophet model — avg fare ───────────────────────────────────────────────
print("\n── Fitting Prophet model (avg fare)...")

df_fare    = monthly[["ds", "avg_fare"]].rename(columns={"avg_fare": "y"})
model_fare = Prophet(
    yearly_seasonality=True,
    weekly_seasonality=False,
    daily_seasonality=False,
    interval_width=0.95,
    changepoint_prior_scale=0.2,
)
model_fare.fit(df_fare)
forecast_fare = model_fare.predict(future)

forecast_out["fare_forecast"] = forecast_fare[
    forecast_fare["ds"] > actual_end]["yhat"].round(2).values
forecast_out["fare_lower"]    = forecast_fare[
    forecast_fare["ds"] > actual_end]["yhat_lower"].round(2).values
forecast_out["fare_upper"]    = forecast_fare[
    forecast_fare["ds"] > actual_end]["yhat_upper"].round(2).values
forecast_out["revenue_forecast"] = (
    forecast_out["trips_forecast"] * forecast_out["fare_forecast"]
).round(0)

print(f"\nFare + Revenue forecast Apr–Dec 2026:")
print(forecast_out[["ds", "fare_forecast", "fare_lower",
                     "fare_upper", "revenue_forecast"]].to_string(index=False))


# ── 4. Model validation: 2026 Q1 actual vs forecast ──────────────────────────
print("\n" + "=" * 60)
print("MODEL VALIDATION: 2026 Q1 actual vs forecast")
print("=" * 60)

actual_2026 = athena_query(f"""
    SELECT
        date_trunc('month', pickup_time)    AS ds,
        COUNT(*)                            AS actual_trips,
        AVG(fare_amount)                    AS actual_fare
    FROM {T}
    WHERE year = 2026
    GROUP BY date_trunc('month', pickup_time)
    ORDER BY date_trunc('month', pickup_time)
""")
actual_2026["ds"] = pd.to_datetime(actual_2026["ds"])

if len(actual_2026) > 0:
    forecast_q1 = forecast[forecast["ds"].isin(actual_2026["ds"])][
        ["ds", "trips_forecast", "trips_lower", "trips_upper"]
    ].copy()
    forecast_q1["trips_forecast"] = np.exp(
        forecast[forecast["ds"].isin(actual_2026["ds"])]["yhat"]
    ).round(0).values

    validation = actual_2026.merge(forecast_q1, on="ds")
    validation["error_pct"] = (
        (validation["actual_trips"] - validation["trips_forecast"])
        / validation["trips_forecast"] * 100
    ).round(2)

    print(validation[["ds", "actual_trips", "trips_forecast",
                       "trips_lower", "trips_upper", "error_pct"]].to_string(index=False))

    mape = validation["error_pct"].abs().mean()
    print(f"\nMAPE: {mape:.2f}%")
    if mape < 10:
        print("→ Model accuracy GOOD (MAPE < 10%)")
    elif mape < 20:
        print("→ Model accuracy ACCEPTABLE (MAPE 10-20%)")
    else:
        print("→ Model accuracy POOR — interpret with caution")


# ── 5. Export ─────────────────────────────────────────────────────────────────
export_csv(forecast_out, "forecast_2026.csv")

full_series = pd.concat([
    monthly[["ds", "trip_count", "avg_fare"]].assign(type="actual"),
    forecast_out[["ds", "trips_forecast", "fare_forecast"]].rename(columns={
        "trips_forecast": "trip_count",
        "fare_forecast":  "avg_fare"
    }).assign(type="forecast")
]).sort_values("ds")
export_csv(full_series, "forecast_full_series.csv")

print("\n✅ Forecast complete.")