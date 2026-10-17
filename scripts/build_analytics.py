"""Publish the research snapshot and already-ingested daily records as monthly Parquet."""
import csv
import json
from pathlib import Path
import boto3
from gridcast.analytics import publish
from gridcast.baselines import load_demand
from gridcast.ingestion import timestamp, write_json

BUCKET = 'gridcast-lake-456112636403-us-east-2'


def main():
    s3 = boto3.Session(profile_name='default',region_name='us-east-2').client('s3')
    demand = {timestamp(t):dict(timestamp_utc=timestamp(t),region='DUK',demand_mw=v)
              for t,v in load_demand([Path('data/processed/demand/DUK/2021-01-01_2025-12-31.csv')],'DUK').items()}
    with Path('data/processed/weather/35.2271_-80.8431/2021-01-01_2025-12-31.csv').open(newline='',encoding='utf-8') as stream:
        weather = {}
        for row in csv.DictReader(stream):
            for k in ('latitude','longitude','temperature_2m','relative_humidity_2m','precipitation','wind_speed_10m'):
                row[k] = float(row[k])
            if row['timestamp_utc'] in weather:
                raise ValueError('Duplicate weather timestamp')
            weather[row['timestamp_utc']] = row
    # Include successful prior cloud imports and their revisions; no live source API calls.
    for source, target in [('demand',demand),('weather',weather)]:
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=BUCKET,Prefix=f'processed/{source}/region=DUK/'):
            for obj in page.get('Contents',[]):
                if obj['Key'].endswith('/data.json'):
                    with s3.get_object(Bucket=BUCKET,Key=obj['Key'])['Body'] as body:
                        for row in json.load(body):
                            target[row['timestamp_utc']] = row
    joined = [{**row,**weather[t]} for t,row in sorted(demand.items()) if t in weather]
    objects = publish(s3,BUCKET,list(demand.values()),list(weather.values()),joined)
    result = dict(demand_rows=len(demand),weather_rows=len(weather),joined_rows=len(joined),objects=objects)
    write_json(Path('reports/parquet_backfill.json'),result)
    print(json.dumps({k:v for k,v in result.items() if k!='objects'}),flush=True)
    print(f'Wrote {len(objects)} Parquet objects',flush=True)


if __name__ == '__main__':
    main()
