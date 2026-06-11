"""
Athena query helper — replaces DuckDB
Executes SQL via Athena, returns pandas DataFrame
"""
import boto3
import pandas as pd
import time
import io

BUCKET    = "nyc-tlc-pricing-588738598819-ap-southeast-1-an"
REGION    = "ap-southeast-1"
WORKGROUP = "nyc-tlc-pricing"
GLUE_DB   = "nyc_tlc_pricing"

athena = boto3.client("athena", region_name=REGION)
s3     = boto3.client("s3",     region_name=REGION)


def query(sql: str, timeout: int = 300) -> pd.DataFrame:
    """Run SQL on Athena, return DataFrame"""
    response = athena.start_query_execution(
        QueryString=sql,
        WorkGroup=WORKGROUP,
    )
    qid = response["QueryExecutionId"]

    # wait for completion
    for _ in range(timeout // 2):
        status = athena.get_query_execution(QueryExecutionId=qid)
        state  = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {state}: {reason}")
        time.sleep(2)
    else:
        raise TimeoutError(f"Query timed out after {timeout}s")

    # get result from S3
    result_key = f"athena-results/{qid}.csv"
    obj = s3.get_object(Bucket=BUCKET, Key=result_key)
    df  = pd.read_csv(io.BytesIO(obj["Body"].read()))
    return df


def execute(sql: str):
    """Run DDL/DML without returning results"""
    response = athena.start_query_execution(
        QueryString=sql,
        WorkGroup=WORKGROUP,
    )
    qid = response["QueryExecutionId"]
    for _ in range(150):
        status = athena.get_query_execution(QueryExecutionId=qid)
        state  = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena {state}: {reason}")
        time.sleep(2)

# convenience: silver_trips SQL for Yellow Taxi
SILVER_YELLOW = f"""
SELECT
    tpep_pickup_datetime                                        AS pickup_time,
    tpep_dropoff_datetime                                       AS dropoff_time,
    year(tpep_pickup_datetime)                                  AS year,
    month(tpep_pickup_datetime)                                 AS month,
    hour(tpep_pickup_datetime)                                  AS pickup_hour,
    day_of_week(tpep_pickup_datetime)                           AS day_of_week,
    quarter(tpep_pickup_datetime)                               AS quarter,
    CASE
        WHEN hour(tpep_pickup_datetime) BETWEEN 7  AND 9  THEN 'morning_rush'
        WHEN hour(tpep_pickup_datetime) BETWEEN 17 AND 19 THEN 'evening_rush'
        WHEN hour(tpep_pickup_datetime) BETWEEN 0  AND 5  THEN 'late_night'
        ELSE 'off_peak'
    END                                                         AS time_bucket,
    CASE WHEN tpep_pickup_datetime >= TIMESTAMP '2025-01-05 00:00:00'
         THEN 1 ELSE 0 END                                      AS is_congestion_era,
    'yellow'                                                    AS dataset,
    pulocationid                                                AS pickup_zone,
    dolocationid                                                AS dropoff_zone,
    fare_amount,
    tip_amount,
    trip_distance,
    passenger_count,
    fare_amount / NULLIF(trip_distance, 0)                      AS fare_per_km,
    COALESCE(CAST(congestion_surcharge AS DOUBLE), 0)           AS congestion_fee,
    NULL                                                        AS wait_time_minutes,
    NULL                                                        AS platform
FROM {GLUE_DB}.yellow_trips
WHERE fare_amount     BETWEEN 2.5 AND 500
  AND trip_distance   BETWEEN 0.1 AND 100
  AND passenger_count BETWEEN 1 AND 6
  AND tpep_pickup_datetime >= TIMESTAMP '2024-01-01 00:00:00'
  AND tpep_pickup_datetime  < TIMESTAMP '2026-07-01 00:00:00'
  AND tpep_dropoff_datetime > tpep_pickup_datetime
  AND date_diff('minute', tpep_pickup_datetime, tpep_dropoff_datetime) BETWEEN 1 AND 180
"""

# convenience: silver_fhv SQL
SILVER_FHV = f"""
SELECT
    pickup_datetime                                             AS pickup_time,
    dropoff_datetime                                            AS dropoff_time,
    year(pickup_datetime)                                       AS year,
    month(pickup_datetime)                                      AS month,
    hour(pickup_datetime)                                       AS pickup_hour,
    day_of_week(pickup_datetime)                                AS day_of_week,
    quarter(pickup_datetime)                                    AS quarter,
    CASE
        WHEN hour(pickup_datetime) BETWEEN 7  AND 9  THEN 'morning_rush'
        WHEN hour(pickup_datetime) BETWEEN 17 AND 19 THEN 'evening_rush'
        WHEN hour(pickup_datetime) BETWEEN 0  AND 5  THEN 'late_night'
        ELSE 'off_peak'
    END                                                         AS time_bucket,
    CASE WHEN pickup_datetime >= TIMESTAMP '2025-01-05 00:00:00'
         THEN 1 ELSE 0 END                                      AS is_congestion_era,
    'fhv'                                                       AS dataset,
    pulocationid                                                AS pickup_zone,
    dolocationid                                                AS dropoff_zone,
    base_passenger_fare                                         AS fare_amount,
    tips                                                        AS tip_amount,
    trip_miles                                                  AS trip_distance,
    1                                                           AS passenger_count,
    base_passenger_fare / NULLIF(trip_miles, 0)                 AS fare_per_km,
    COALESCE(CAST(congestion_surcharge AS DOUBLE), 0)           AS congestion_fee,
    date_diff('minute', request_datetime, pickup_datetime)      AS wait_time_minutes,
    CASE hvfhs_license_num
        WHEN 'HV0003' THEN 'Uber'
        WHEN 'HV0005' THEN 'Lyft'
        ELSE 'Other'
    END                                                         AS platform
FROM {GLUE_DB}.fhv_trips
WHERE base_passenger_fare  BETWEEN 2.5 AND 500
  AND trip_miles           BETWEEN 0.1 AND 100
  AND pickup_datetime      >= TIMESTAMP '2024-01-01 00:00:00'
  AND pickup_datetime       < TIMESTAMP '2026-07-01 00:00:00'
  AND dropoff_datetime      > pickup_datetime
  AND date_diff('minute', pickup_datetime, dropoff_datetime) BETWEEN 1 AND 180
  AND date_diff('minute', request_datetime, pickup_datetime) BETWEEN 0 AND 60
"""