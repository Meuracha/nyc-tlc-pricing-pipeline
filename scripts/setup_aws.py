"""
Setup AWS infrastructure (run once):
1. Glue Database
2. Glue Tables with year partition for Yellow + FHV (2022-2026)
3. Athena Workgroup
4. Test query
"""
import boto3
import time

BUCKET    = "nyc-tlc-pricing-588738598819-ap-southeast-1-an"
REGION    = "ap-southeast-1"
GLUE_DB   = "nyc_tlc_pricing"
WORKGROUP = "nyc-tlc-pricing"

glue   = boto3.client("glue",   region_name=REGION)
athena = boto3.client("athena", region_name=REGION)


# ── 1. Glue Database ──────────────────────────────────────────────────────────
print("1. Creating Glue database...")
try:
    glue.create_database(DatabaseInput={"Name": GLUE_DB})
    print(f"   ✅ {GLUE_DB}")
except glue.exceptions.AlreadyExistsException:
    print(f"   Already exists: {GLUE_DB}")


# ── 2. Yellow Taxi table (partitioned by year) ────────────────────────────────
print("\n2. Creating Glue table: yellow_trips (partitioned by year 2022-2026)...")
try:
    glue.create_table(
        DatabaseName=GLUE_DB,
        TableInput={
            "Name": "yellow_trips",
            "StorageDescriptor": {
                "Columns": [
                    {"Name": "tpep_pickup_datetime",  "Type": "timestamp"},
                    {"Name": "tpep_dropoff_datetime", "Type": "timestamp"},
                    {"Name": "pulocationid",          "Type": "int"},
                    {"Name": "dolocationid",          "Type": "int"},
                    {"Name": "fare_amount",           "Type": "double"},
                    {"Name": "tip_amount",            "Type": "double"},
                    {"Name": "trip_distance",         "Type": "double"},
                    {"Name": "passenger_count",       "Type": "bigint"},
                    {"Name": "congestion_surcharge",  "Type": "double"},
                ],
                "Location": f"s3://{BUCKET}/raw/yellow/",
                "InputFormat":  "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                "SerdeInfo": {
                    "SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                },
            },
            "PartitionKeys": [{"Name": "year", "Type": "int"}],
            "TableType": "EXTERNAL_TABLE",
            "Parameters": {
                "classification":            "parquet",
                "projection.enabled":        "true",
                "projection.year.type":      "integer",
                "projection.year.range":     "2022,2026",
                "storage.location.template": "s3://" + BUCKET + "/raw/yellow/year=${year}",
            },
        }
    )
    print("   ✅ yellow_trips")
except glue.exceptions.AlreadyExistsException:
    print("   Already exists: yellow_trips")


# ── 3. FHV table (partitioned by year) ───────────────────────────────────────
print("\n3. Creating Glue table: fhv_trips (partitioned by year 2022-2026)...")
try:
    glue.create_table(
        DatabaseName=GLUE_DB,
        TableInput={
            "Name": "fhv_trips",
            "StorageDescriptor": {
                "Columns": [
                    {"Name": "hvfhs_license_num",    "Type": "string"},
                    {"Name": "request_datetime",     "Type": "timestamp"},
                    {"Name": "on_scene_datetime",    "Type": "timestamp"},
                    {"Name": "pickup_datetime",      "Type": "timestamp"},
                    {"Name": "dropoff_datetime",     "Type": "timestamp"},
                    {"Name": "pulocationid",         "Type": "int"},
                    {"Name": "dolocationid",         "Type": "int"},
                    {"Name": "trip_miles",           "Type": "double"},
                    {"Name": "trip_time",            "Type": "bigint"},
                    {"Name": "base_passenger_fare",  "Type": "double"},
                    {"Name": "tolls",                "Type": "double"},
                    {"Name": "congestion_surcharge", "Type": "double"},
                    {"Name": "tips",                 "Type": "double"},
                    {"Name": "driver_pay",           "Type": "double"},
                    {"Name": "shared_request_flag",  "Type": "string"},
                    {"Name": "shared_match_flag",    "Type": "string"},
                ],
                "Location": f"s3://{BUCKET}/raw/fhv/",
                "InputFormat":  "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                "SerdeInfo": {
                    "SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                },
            },
            "PartitionKeys": [{"Name": "year", "Type": "int"}],
            "TableType": "EXTERNAL_TABLE",
            "Parameters": {
                "classification":            "parquet",
                "projection.enabled":        "true",
                "projection.year.type":      "integer",
                "projection.year.range":     "2022,2026",
                "storage.location.template": "s3://" + BUCKET + "/raw/fhv/year=${year}",
            },
        }
    )
    print("   ✅ fhv_trips")
except glue.exceptions.AlreadyExistsException:
    print("   Already exists: fhv_trips")


# ── 4. Athena Workgroup ───────────────────────────────────────────────────────
print("\n4. Creating Athena workgroup...")
try:
    athena.create_work_group(
        Name=WORKGROUP,
        Configuration={
            "ResultConfiguration": {
                "OutputLocation": f"s3://{BUCKET}/athena-results/",
            },
            "EnforceWorkGroupConfiguration": True,
            "PublishCloudWatchMetricsEnabled": False,
        },
        Description="NYC TLC Pricing Analytics"
    )
    print(f"   ✅ {WORKGROUP}")
except athena.exceptions.InvalidRequestException:
    print(f"   Already exists: {WORKGROUP}")


# ── 5. Test query ─────────────────────────────────────────────────────────────
print("\n5. Testing Athena partition query...")

def run_query(sql):
    resp = athena.start_query_execution(QueryString=sql, WorkGroup=WORKGROUP)
    qid  = resp["QueryExecutionId"]
    for _ in range(30):
        status = athena.get_query_execution(QueryExecutionId=qid)
        state  = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return athena.get_query_results(QueryExecutionId=qid)["ResultSet"]["Rows"]
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"{state}: {reason}")
        time.sleep(2)

try:
    rows = run_query(f"""
        SELECT year, COUNT(*) AS trips
        FROM {GLUE_DB}.yellow_trips
        WHERE year IN (2022, 2023, 2024, 2025, 2026)
        GROUP BY year ORDER BY year
    """)
    print("   ✅ Partition query working:")
    for row in rows[1:]:
        yr = row["Data"][0]["VarCharValue"]
        ct = row["Data"][1]["VarCharValue"]
        print(f"      year={yr}: {int(ct):,} trips")
except Exception as e:
    print(f"   ❌ {e}")

print(f"\n✅ AWS setup complete")
print(f"Glue DB   : {GLUE_DB}")
print(f"Tables    : yellow_trips, fhv_trips")
print(f"Workgroup : {WORKGROUP}")
print(f"Years     : 2022–2026 (partition projection)")