"""
Difference-in-Differences (DiD) Analysis
Causal estimate of congestion pricing impact on demand

Natural experiment:
  NYC Congestion Relief Zone toll started January 5, 2025
  Treatment: Manhattan CBD zones (directly affected)
  Control  : Outer borough zones (not directly affected)
  Before   : 2024 full year
  After    : 2025 full year

Maps to JD: "Impact Tracking" + "Experimentation" + "Monitor Performance"
"""
import sys
sys.path.insert(0, '.')
from scripts.athena_connect import query as athena_query, GLUE_DB
import pandas as pd
import numpy as np
from scipy import stats
import boto3 as _boto3
import io as _io

try:
    import statsmodels.formula.api as smf
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

_s3     = _boto3.client("s3", region_name="ap-southeast-1")
_BUCKET = "nyc-tlc-pricing-588738598819-ap-southeast-1-an"

def export_csv(df, filename):
    buf = _io.StringIO()
    df.to_csv(buf, index=False)
    _s3.put_object(Bucket=_BUCKET, Key=f"export/{filename}",
                   Body=buf.getvalue().encode("utf-8"), ContentType="text/csv")
    print(f"  → s3://{_BUCKET}/export/{filename}")

T = f"{GLUE_DB}.silver_yellow"

CBD_ZONES = [
    4, 12, 13, 24, 41, 42, 43, 45, 48, 50, 68, 79, 87, 88,
    90, 100, 107, 113, 114, 116, 120, 125, 127, 128, 137,
    140, 141, 142, 143, 144, 148, 151, 152, 158, 161, 162,
    163, 164, 166, 170, 186, 194, 202, 209, 211, 224, 229,
    230, 231, 232, 233, 234, 236, 237, 238, 239, 249, 261, 262
]

print("=" * 65)
print("DIFFERENCE-IN-DIFFERENCES (DiD) ANALYSIS")
print("Natural experiment: NYC Congestion Pricing (Jan 5, 2025)")
print("=" * 65)
print(f"\nTreatment (CBD zones)    : {len(CBD_ZONES)} zones")
print(f"Control  (non-CBD zones) : all other zones")
print(f"Before period            : 2024 full year")
print(f"After period             : 2025 full year")


# ── 1. Build monthly panel ────────────────────────────────────────────────────
print("\nBuilding monthly panel data...")

panel = athena_query(f"""
    SELECT
        year,
        month(pickup_time)                          AS month,
        pickup_zone,
        CASE WHEN pickup_zone IN ({','.join(map(str, CBD_ZONES))})
             THEN 1 ELSE 0 END                      AS is_cbd,
        COUNT(*)                                    AS trip_count,
        AVG(fare_amount)                            AS avg_fare,
        AVG(fare_per_km)                            AS avg_fare_per_km,
        AVG(trip_distance)                          AS avg_distance,
        AVG(congestion_fee)                         AS avg_congestion_fee,
        SUM(fare_amount)                            AS total_revenue
    FROM {T}
    WHERE year IN (2024, 2025)
    GROUP BY year, month(pickup_time), pickup_zone,
        CASE WHEN pickup_zone IN ({','.join(map(str, CBD_ZONES))})
             THEN 1 ELSE 0 END
    ORDER BY pickup_zone, year, month(pickup_time)
""")

panel["post"]      = (panel["year"] == 2025).astype(int)
panel["treated"]   = panel["is_cbd"]
panel["did"]       = panel["post"] * panel["treated"]
panel["log_trips"] = np.log1p(panel["trip_count"])

print(f"Panel observations : {len(panel):,}")
print(f"CBD zones          : {panel[panel['is_cbd']==1]['pickup_zone'].nunique()}")
print(f"Non-CBD zones      : {panel[panel['is_cbd']==0]['pickup_zone'].nunique()}")


# ── 2. Simple DiD ─────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("1. SIMPLE DiD CALCULATION")
print("=" * 65)

cbd_before    = panel[(panel["treated"]==1) & (panel["post"]==0)]["trip_count"].mean()
cbd_after     = panel[(panel["treated"]==1) & (panel["post"]==1)]["trip_count"].mean()
noncbd_before = panel[(panel["treated"]==0) & (panel["post"]==0)]["trip_count"].mean()
noncbd_after  = panel[(panel["treated"]==0) & (panel["post"]==1)]["trip_count"].mean()

did_estimate  = (cbd_after - cbd_before) - (noncbd_after - noncbd_before)
cbd_change    = (cbd_after - cbd_before) / cbd_before * 100
noncbd_change = (noncbd_after - noncbd_before) / noncbd_before * 100
did_pct       = did_estimate / cbd_before * 100

print(f"CBD    before → after : {cbd_before:>8,.0f} → {cbd_after:>8,.0f}  ({cbd_change:+.2f}%)")
print(f"NonCBD before → after : {noncbd_before:>8,.0f} → {noncbd_after:>8,.0f}  ({noncbd_change:+.2f}%)")
print(f"\nDiD estimate          : {did_estimate:>+8,.0f} trips/zone/month")
print(f"DiD effect (%)        : {did_pct:>+8.2f}%")
print(f"\nInterpretation: Congestion pricing caused additional")
print(f"  {abs(did_pct):.2f}% {'reduction' if did_pct < 0 else 'increase'} in CBD demand")
print(f"  beyond the trend observed in non-CBD zones")


# ── 3. DiD fare effect ────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("2. DiD FARE EFFECT")
print("=" * 65)

cbd_fare_before    = panel[(panel["treated"]==1) & (panel["post"]==0)]["avg_fare"].mean()
cbd_fare_after     = panel[(panel["treated"]==1) & (panel["post"]==1)]["avg_fare"].mean()
noncbd_fare_before = panel[(panel["treated"]==0) & (panel["post"]==0)]["avg_fare"].mean()
noncbd_fare_after  = panel[(panel["treated"]==0) & (panel["post"]==1)]["avg_fare"].mean()

did_fare = (cbd_fare_after - cbd_fare_before) - (noncbd_fare_after - noncbd_fare_before)

print(f"CBD    avg fare before → after : ${cbd_fare_before:.2f} → ${cbd_fare_after:.2f}  ({cbd_fare_after-cbd_fare_before:+.2f})")
print(f"NonCBD avg fare before → after : ${noncbd_fare_before:.2f} → ${noncbd_fare_after:.2f}  ({noncbd_fare_after-noncbd_fare_before:+.2f})")
print(f"\nDiD fare effect : ${did_fare:+.4f}")


# ── 4. OLS regression ─────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("3. OLS REGRESSION DiD")
print("=" * 65)

did_coef = 0
did_pval = 1.0
did_effect_pct = 0

if HAS_STATSMODELS:
    model = smf.ols(
        "log_trips ~ post + treated + did + C(month)",
        data=panel
    ).fit(cov_type="HC3")

    print(model.summary().tables[1])

    did_coef       = model.params["did"]
    did_pval       = model.pvalues["did"]
    did_ci         = model.conf_int().loc["did"]
    did_effect_pct = (np.exp(did_coef) - 1) * 100

    print(f"\n── DiD coefficient ──")
    print(f"  Effect (% change) : {did_effect_pct:+.2f}%")
    print(f"  P-value           : {did_pval:.4f}")
    print(f"  Significant       : {'YES ✅' if did_pval < 0.05 else 'NO ❌'}")
    print(f"  95% CI (% effect) : ({(np.exp(did_ci[0])-1)*100:.2f}%, {(np.exp(did_ci[1])-1)*100:.2f}%)")
    print(f"  R-squared         : {model.rsquared:.4f}")


# ── 5. Parallel trends ────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("4. PARALLEL TRENDS CHECK (2024 pre-period)")
print("=" * 65)

trends = panel[panel["year"] == 2024].groupby(
    ["month", "treated"]
)["trip_count"].mean().unstack()
trends.columns    = ["non_CBD", "CBD"]
trends["cbd_g"]   = trends["CBD"].pct_change() * 100
trends["noncbd_g"]= trends["non_CBD"].pct_change() * 100
trends["diff"]    = trends["cbd_g"] - trends["noncbd_g"]

print(trends.round(2).to_string())
avg_diff = trends["diff"].abs().mean()
print(f"\nAvg monthly trend divergence: {avg_diff:.2f}%")
if avg_diff < 5:
    print("✅ Parallel trends assumption likely holds")
else:
    print("⚠️  Parallel trends may be violated — interpret with caution")


# ── 6. Implied elasticity ─────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("5. IMPLIED PRICE ELASTICITY FROM DiD")
print("=" * 65)

avg_congestion_fee = panel[
    (panel["treated"]==1) & (panel["post"]==1)
]["avg_congestion_fee"].mean()

pct_price_change   = avg_congestion_fee / cbd_fare_before * 100
implied_elasticity = did_pct / pct_price_change if pct_price_change != 0 else 0

print(f"Avg congestion fee    : ${avg_congestion_fee:.2f}")
print(f"Avg CBD fare before   : ${cbd_fare_before:.2f}")
print(f"% price change        : {pct_price_change:+.2f}%")
print(f"% demand change (DiD) : {did_pct:+.2f}%")
print(f"\nImplied elasticity    : {implied_elasticity:.4f}")
print(f"Assumed in A/B        : -0.3000")

if abs(implied_elasticity) < 0.3:
    print("→ Demand MORE inelastic than assumed — fee increase loses fewer trips")
else:
    print("→ Demand MORE elastic than assumed — fee increase loses more trips")


# ── 7. Business recommendation ────────────────────────────────────────────────
print("\n" + "=" * 65)
print("6. BUSINESS RECOMMENDATION")
print("=" * 65)

print(f"DiD effect            : {did_pct:+.2f}% demand change in CBD")
print(f"Implied elasticity    : {implied_elasticity:.4f}")
print(f"Significant           : {'YES ✅' if did_pval < 0.05 else 'NO ❌'}")
print()

if did_pct < -5:
    print("→ Significant demand reduction — avoid fee increases in CBD")
elif did_pct < 0:
    print("→ Mild reduction — modest fee increase in CBD is defensible")
    print("  Monitor monthly for lagged behavioral change")
else:
    print("→ No reduction — fee optimization opportunity in CBD zones")


# ── 8. Export ─────────────────────────────────────────────────────────────────
export_csv(panel, "did_panel.csv")

did_summary = pd.DataFrame([{
    "method":               "difference_in_differences",
    "treatment":            "manhattan_cbd_zones",
    "policy_event":         "nyc_congestion_pricing_jan2025",
    "cbd_zones":            len(CBD_ZONES),
    "cbd_demand_change_pct":    round(cbd_change, 2),
    "noncbd_demand_change_pct": round(noncbd_change, 2),
    "did_estimate_trips":   round(did_estimate, 0),
    "did_effect_pct":       round(did_pct, 2),
    "did_fare_effect":      round(did_fare, 4),
    "avg_congestion_fee":   round(avg_congestion_fee, 2),
    "implied_elasticity":   round(implied_elasticity, 4),
    "assumed_elasticity":   -0.3,
    "did_regression_pval":  round(did_pval, 4) if HAS_STATSMODELS else None,
    "did_effect_pct_reg":   round(did_effect_pct, 2) if HAS_STATSMODELS else None,
}])
export_csv(did_summary, "did_summary.csv")

print("\n✅ DiD analysis complete.")
print("\n── What DiD gives us that simulation cannot ──")
print("  1. Causal estimate — not assumption-based")
print("  2. Real elasticity from observed behavior")
print("  3. Parallel trends validation")
print("  4. Regression with month fixed effects")
print("  5. Defensible in interview with econometric grounding")