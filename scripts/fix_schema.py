"""
Fix schema inconsistency in Yellow Taxi 2022-2023
passenger_count = double in 2022-2023, int64 in 2024-2025

Fix: download from S3 → cast to int64 → upload back to S3
No re-download from NYC TLC needed
"""
import boto3
import io
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

BUCKET = "nyc-tlc-pricing-588738598819-ap-southeast-1-an"
REGION = "ap-southeast-1"
YEARS  = [2022, 2023]

s3 = boto3.client("s3", region_name=REGION)


def fix_parquet(key: str):
    """Download, cast passenger_count to int64, upload back"""

    # ── download ──────────────────────────────────────────────
    obj  = s3.get_object(Bucket=BUCKET, Key=key)
    buf  = io.BytesIO(obj["Body"].read())
    table = pq.read_table(buf)

    # ── check if fix needed ───────────────────────────────────
    schema = table.schema
    idx    = schema.get_field_index("passenger_count")

    if idx == -1:
        print(f"    No passenger_count column — skip")
        return False

    current_type = schema.field(idx).type
    if current_type == pa.int64():
        print(f"    Already int64 — skip")
        return False

    print(f"    passenger_count: {current_type} → int64")

    # ── cast passenger_count to int64 ─────────────────────────
    new_col    = table.column("passenger_count").cast(pa.int64(), safe=False)
    table      = table.set_column(idx, "passenger_count", new_col)

    # ── upload back to S3 ─────────────────────────────────────
    out = io.BytesIO()
    pq.write_table(table, out, compression="snappy")
    out.seek(0)
    size = out.getbuffer().nbytes

    with tqdm(total=size, unit="B", unit_scale=True, leave=False) as bar:
        s3.upload_fileobj(
            out, BUCKET, key,
            Callback=lambda x: bar.update(x)
        )

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("Fix passenger_count schema: double → int64")
    print(f"Years: {YEARS}")
    print("=" * 60)

    total_fixed = 0
    total_files = 0

    for year in YEARS:
        print(f"\nYear {year}:")

        # list all parquet files for this year
        prefix   = f"raw/yellow/year={year}/"
        paginator = s3.get_paginator("list_objects_v2")
        pages    = paginator.paginate(Bucket=BUCKET, Prefix=prefix)

        files = []
        for page in pages:
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".parquet"):
                    files.append(obj["Key"])

        print(f"  Found {len(files)} files")

        for key in sorted(files):
            total_files += 1
            fname = key.split("/")[-1]
            print(f"  [{total_files}] {fname}")
            try:
                fixed = fix_parquet(key)
                if fixed:
                    total_fixed += 1
                    print(f"    ✅ Fixed")
                else:
                    print(f"    ⏭️  Skipped")
            except Exception as e:
                print(f"    ❌ Error: {e}")

    print(f"\n{'='*60}")
    print(f"✅ Complete: {total_fixed}/{total_files} files fixed")
    print(f"\nNext steps:")
    print(f"  1. python3 scripts/setup_aws.py  (update passenger_count to bigint)")
    print(f"  2. python3 scripts/transform.py")
    print(f"  3. python3 scripts/forecast.py")