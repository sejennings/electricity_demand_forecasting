"""Bounded, versioned historical ingestion for Lambda and Step Functions."""
import csv
import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from gridcast.ingestion import demand_rows, weather_rows, quality


def window(event):
    end = date.fromisoformat(event['end_date']) if event.get('end_date') else datetime.now(timezone.utc).date() - timedelta(days=7)
    days = int(event.get('days', 7))
    if not 1 <= days <= 7:
        raise ValueError('Each invocation must cover 1–7 days')
    if end > datetime.now(timezone.utc).date() - timedelta(days=7):
        raise ValueError('ERA5 historical pipeline requires at least seven days of lag')
    return end - timedelta(days=days-1), end


def partition(day):
    return f'region=DUK/year={day.year}/month={day.month:02}/day={day.day:02}'


def put_json(s3, bucket, key, value):
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(value).encode(),
                  ContentType='application/json', ServerSideEncryption='AES256')


def get_json(s3, bucket, key):
    with s3.get_object(Bucket=bucket, Key=key)['Body'] as stream:
        return json.load(stream)


def validate(rows, first, last, columns):
    report = quality(rows, first, last, columns)
    if report['missing_hours'] or any(report['null_values'].values()):
        raise ValueError(f'Incomplete hourly data: {report}')
    if 'demand_mw' in columns and any(r['demand_mw'] <= 0 for r in rows):
        raise ValueError('Demand must be positive')
    return report


def ingest(event, s3, secrets):
    first, last = window(event)
    bucket = os.environ['LAKE_BUCKET']
    source = event['source']
    if source not in ('demand', 'weather'):
        raise ValueError('Unknown source')
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        if source == 'demand':
            key = secrets.get_secret_value(SecretId=os.environ['EIA_SECRET_ARN'])['SecretString']
            rows = demand_rows(first, last, 'DUK', root, key)
            columns = ['demand_mw']
        else:
            rows = weather_rows(first, last, 35.2271, -80.8431, root)
            columns = ['temperature_2m', 'relative_humidity_2m', 'precipitation', 'wind_speed_10m']
        # Persist source evidence even if validation fails. Keys are execution-scoped.
        run = event['run_id']
        for path in root.rglob('*.json'):
            key = f'raw/{source}/{partition(first)}/run={run}/{path.name}'
            s3.upload_file(str(path), bucket, key, ExtraArgs={'ContentType': 'application/json', 'ServerSideEncryption': 'AES256'})
        report = quality(rows, first, last, columns)
        put_json(s3, bucket, f'reports/{source}/run={run}.json', report)
        validate(rows, first, last, columns)
        day = first
        while day <= last:
            daily = [r for r in rows if r['timestamp_utc'].startswith(str(day))]
            put_json(s3, bucket, f'processed/{source}/{partition(day)}/data.json', daily)
            day += timedelta(days=1)
    return {'source': source, **report}


def curate(event, s3):
    first, last = window(event)
    bucket = os.environ['LAKE_BUCKET']
    day = first
    count = 0
    all_demand, all_weather, all_joined = [], [], []
    while day <= last:
        prefix = partition(day)
        demand = get_json(s3, bucket, f'processed/demand/{prefix}/data.json')
        weather = get_json(s3, bucket, f'processed/weather/{prefix}/data.json')
        validate(demand, day, day, ['demand_mw'])
        validate(weather, day, day, ['temperature_2m', 'relative_humidity_2m', 'precipitation', 'wind_speed_10m'])
        by_time = {r['timestamp_utc']: r for r in weather}
        rows = [{**r, **{k:v for k,v in by_time[r['timestamp_utc']].items() if k != 'timestamp_utc'}} for r in demand]
        all_demand.extend(demand)
        all_weather.extend(weather)
        all_joined.extend(rows)
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
        s3.put_object(Bucket=bucket, Key=f'curated/hourly/{prefix}/data.csv', Body=output.getvalue().encode(),
                      ContentType='text/csv', ServerSideEncryption='AES256')
        count += len(rows)
        day += timedelta(days=1)
    from gridcast.analytics import publish
    parquet = publish(s3, bucket, all_demand, all_weather, all_joined)
    result = {'rows': count, 'start': str(first), 'end': str(last), 'weather_use': 'historical reanalysis only',
              'parquet_objects': len(parquet)}
    put_json(s3, bucket, f'reports/pipeline/run={event["run_id"]}.json', result)
    return result


def handler(event, context):
    import boto3
    s3 = boto3.client('s3')
    if event.get('action') == 'curate':
        return curate(event, s3)
    return ingest(event, s3, boto3.client('secretsmanager'))
