"""Upload the existing research snapshot, excluding model binaries and the bulk ZIP."""
import argparse
from pathlib import Path
import boto3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bucket', required=True)
    args = parser.parse_args()
    client = boto3.Session(profile_name='default', region_name='us-east-2').client('s3')
    mappings = [
        (Path('data/raw/eia/DUK/bulk_series.json'), 'raw/history/eia/DUK/bulk_series.json'),
        (Path('data/processed/demand/DUK/2021-01-01_2025-12-31.csv'), 'processed/history/demand/DUK/2021-01-01_2025-12-31.csv'),
        (Path('data/processed/weather/35.2271_-80.8431/2021-01-01_2025-12-31.csv'), 'processed/history/weather/35.2271_-80.8431/2021-01-01_2025-12-31.csv'),
        (Path('reports/backfill_quality.json'), 'reports/history/backfill_quality.json'),
    ]
    for path in Path('data/raw/weather/35.2271_-80.8431').glob('*.json'):
        mappings.append((path, f'raw/history/weather/35.2271_-80.8431/{path.name}'))
    # Validate all local inputs before writing any objects.
    for path, _ in mappings:
        if not path.is_file():
            raise FileNotFoundError(path)
    for path, key in mappings:
        client.upload_file(str(path), args.bucket, key, ExtraArgs={'ServerSideEncryption':'AES256'})
    print(f'Uploaded {len(mappings)} historical data objects to {args.bucket}')


if __name__ == '__main__':
    main()
