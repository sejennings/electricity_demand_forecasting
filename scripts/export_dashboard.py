"""Export a read-only dashboard snapshot. No AWS credentials enter the browser."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import boto3
from botocore.config import Config
from gridcast.baselines import metrics

BUCKET = 'gridcast-lake-456112636403-us-east-2'


def read(s3, key):
    with s3.get_object(Bucket=BUCKET, Key=key)['Body'] as body:
        return json.load(body)


def build_run(manifest, score=None):
    raw = manifest['forecast_csv']
    if hashlib.sha256(raw.encode()).hexdigest() != manifest['forecast_sha256']:
        raise ValueError('Forecast integrity check failed')
    if score and (score['forecast_sha256'] != manifest['forecast_sha256'] or
                  score['issue_time_utc'] != manifest['issue_time_utc']):
        raise ValueError('Score does not belong to this forecast issue')
    actuals = {r['timestamp_utc']: r['actual_mw'] for r in (score or {}).get('rows', [])}
    rows = [dict(timestamp_utc=r['timestamp_utc'], horizon_hours=int(r['horizon_hours']),
                 forecast_mw=float(r['forecast_mw']), actual_mw=actuals.get(r['timestamp_utc']))
            for r in csv.DictReader(io.StringIO(raw))]
    scored = [r for r in rows if r['actual_mw'] is not None]
    return dict(id=manifest['forecast_id'], issue_time_utc=manifest['issue_time_utc'],
                origin_utc=manifest['forecast_origin_utc'], rows=rows, metrics=metrics(scored),
                status='complete' if len(scored)==len(rows) else 'partial' if scored else 'pending',
                scored_hours=len(scored), pending_hours=len(rows)-len(scored),
                scored_at_utc=(score or {}).get('scored_at_utc'),
                model_sha256=manifest['model_sha256'], image_uri=manifest.get('image_uri'))


def export(session, limit):
    s3 = session.client('s3', config=Config(connect_timeout=10, read_timeout=30,
                                          retries={'mode':'standard','total_max_attempts':3}))
    keys = [o['Key'] for page in s3.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix='forecasts/runs/')
            for o in page.get('Contents', []) if o['Key'].endswith('/manifest.json')]
    # Sort by actual issue time, never UUID/execution-name order.
    manifests = sorted((read(s3, k) for k in keys), key=lambda m:m['issue_time_utc'], reverse=True)[:limit]
    runs = []
    for manifest in manifests:
        pointer = f"scores/runs/{manifest['forecast_id']}/latest.json"
        present = any(o['Key']==pointer for o in s3.list_objects_v2(Bucket=BUCKET, Prefix=pointer, MaxKeys=1).get('Contents', []))
        score = read(s3, read(s3, pointer)['score_key']) if present else None
        runs.append(build_run(manifest, score))
    sf = session.client('stepfunctions', config=Config(connect_timeout=10, read_timeout=30))
    pipelines = []
    for name in ['gridcast-ingestion', 'gridcast-forecast']:
        records = sf.list_executions(stateMachineArn=f'arn:aws:states:us-east-2:456112636403:stateMachine:{name}', maxResults=5)['executions']
        pipelines.append(dict(name=name, executions=[dict(name=r['name'],status=r['status'],
            started_at_utc=r['startDate'].astimezone(timezone.utc).isoformat()) for r in records]))
    return dict(generated_at_utc=datetime.now(timezone.utc).isoformat(), demo=False, region='DUK',
                runs=runs, pipelines=pipelines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('dashboard/snapshot.json'))
    parser.add_argument('--profile',default='default')
    parser.add_argument('--limit',type=int,default=30)
    args=parser.parse_args()
    if not 1<=args.limit<=100: parser.error('limit must be 1–100')
    payload=export(boto3.Session(profile_name=args.profile,region_name='us-east-2'),args.limit)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temporary=args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload,allow_nan=False),encoding='utf-8')
    temporary.replace(args.output)
    print(f"Exported {len(payload['runs'])} forecast issues to {args.output}")


if __name__=='__main__': main()
