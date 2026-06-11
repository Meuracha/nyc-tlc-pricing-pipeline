"""
Ingest NYC TLC data directly from web → S3 (partitioned by year)
No local storage — streams directly via multipart upload

S3 structure:
  raw/yellow/year=2024/yellow_tripdata_2024-01.parquet
  raw/yellow/year=2025/yellow_tripdata_2025-01.parquet
  raw/fhv/year=2024/fhvhv_tripdata_2024-01.parquet
  ...
"""
import boto3
import requests
from tqdm import tqdm

BUCKET   = "nyc-tlc-pricing-588738598819-ap-southeast-1-an"
REGION   = "ap-southeast-1"
BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"

MONTHS = {
    2022: [f"2022-{m:02d}" for m in range(1, 13)],
    2023: [f"2023-{m:02d}" for m in range(1, 13)],
    2024: [f"2024-{m:02d}" for m in range(1, 13)],
    2025: [f"2025-{m:02d}" for m in range(1, 13)],
    2026: [f"2026-{m:02d}" for m in range(1, 4)],
}

DATASETS = [
    {
        "name"     : "Yellow Taxi",
        "filename" : lambda m: f"yellow_tripdata_{m}.parquet",
        "s3_prefix": "raw/yellow",
    },
    {
        "name"     : "High Volume FHV (Uber/Lyft)",
        "filename" : lambda m: f"fhvhv_tripdata_{m}.parquet",
        "s3_prefix": "raw/fhv",
    },
]

s3 = boto3.client("s3", region_name=REGION)


def s3_exists(s3_key: str) -> bool:
    try:
        s3.head_object(Bucket=BUCKET, Key=s3_key)
        return True
    except:
        return False


def stream_to_s3(url: str, s3_key: str):
    """Stream directly from URL to S3 — no local storage"""
    r = requests.get(url, stream=True)
    r.raise_for_status()
    total    = int(r.headers.get("content-length", 0))
    mpu      = s3.create_multipart_upload(Bucket=BUCKET, Key=s3_key)
    upload_id = mpu["UploadId"]
    parts    = []
    part_num = 1
    buffer   = b""
    MIN_PART = 5 * 1024 * 1024  # 5MB min per S3 part

    try:
        with tqdm(total=total, unit="B", unit_scale=True) as bar:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                buffer += chunk
                bar.update(len(chunk))
                if len(buffer) >= MIN_PART:
                    part = s3.upload_part(
                        Bucket=BUCKET, Key=s3_key,
                        UploadId=upload_id, PartNumber=part_num, Body=buffer
                    )
                    parts.append({"PartNumber": part_num, "ETag": part["ETag"]})
                    part_num += 1
                    buffer = b""

            if buffer:
                part = s3.upload_part(
                    Bucket=BUCKET, Key=s3_key,
                    UploadId=upload_id, PartNumber=part_num, Body=buffer
                )
                parts.append({"PartNumber": part_num, "ETag": part["ETag"]})

        s3.complete_multipart_upload(
            Bucket=BUCKET, Key=s3_key,
            MultipartUpload={"Parts": parts}, UploadId=upload_id
        )

    except Exception as e:
        s3.abort_multipart_upload(Bucket=BUCKET, Key=s3_key, UploadId=upload_id)
        raise e


if __name__ == "__main__":
    total_files = sum(len(v) for v in MONTHS.values()) * len(DATASETS)
    job = 0

    for dataset in DATASETS:
        print(f"\n{'='*60}")
        print(f"Dataset: {dataset['name']}")
        print(f"{'='*60}")

        for year, months in MONTHS.items():
            print(f"\n  Year: {year}")

            for month in months:
                job += 1
                filename = dataset["filename"](month)
                # partitioned by year
                s3_key   = f"{dataset['s3_prefix']}/year={year}/{filename}"
                url      = f"{BASE_URL}/{filename}"

                print(f"  [{job}/{total_files}] {filename}")

                if s3_exists(s3_key):
                    print(f"    Already on S3 — skip")
                    continue

                try:
                    print(f"    Streaming web → S3...")
                    stream_to_s3(url, s3_key)
                    print(f"    ✅ s3://{BUCKET}/{s3_key}")
                except Exception as e:
                    print(f"    ❌ {e}")

    print(f"\n✅ Ingest complete")
    print(f"  s3://{BUCKET}/raw/yellow/year=YYYY/")
    print(f"  s3://{BUCKET}/raw/fhv/year=YYYY/")