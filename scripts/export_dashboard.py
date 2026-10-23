"""Export a read-only dashboard snapshot. No AWS credentials enter the browser."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
import tempfile
from pathlib import Path
import boto3
from botocore.config import Config
from gridcast.baselines import metrics
from gridcast.scoring import parse_time
from gridcast.ingestion import timestamp

BUCKET = 'gridcast-lake-456112636403-us-east-2'


def read(s3, key):
    with s3.get_object(Bucket=BUCKET, Key=key)['Body'] as body:
        return json.load(body)


def build_run(manifest, score=None):
    raw = manifest['forecast_csv']
    if hashlib.sha256(raw.encode()).hexdigest() != manifest['forecast_sha256']:
        raise ValueError('Forecast integrity check failed')
    if score and (score['forecast_sha256'] != manifest['forecast_sha256'] or
                  parse_time(score['issue_time_utc']) != parse_time(manifest['issue_time_utc']) or
                  score.get('model_sha256', manifest['model_sha256']) != manifest['model_sha256']):
        raise ValueError('Score does not belong to this forecast issue')
    rows = []
    origin = parse_time(manifest['forecast_origin_utc'])
    if origin <= parse_time(manifest['issue_time_utc']):
        raise ValueError('Forecast origin must follow its issue time')
    for i, row in enumerate(csv.DictReader(io.StringIO(raw))):
        target = parse_time(row['timestamp_utc'])
        prediction = float(row['forecast_mw'])
        if (target != origin + timedelta(hours=i) or int(row['horizon_hours']) != i+1 or
                not math.isfinite(prediction) or prediction <= 0):
            raise ValueError('Invalid forecast hour, horizon or demand')
        if row.get('issue_time_utc') and parse_time(row['issue_time_utc']) != parse_time(manifest['issue_time_utc']):
            raise ValueError('Forecast rows contain a different issue time')
        rows.append(dict(timestamp_utc=timestamp(target), horizon_hours=i+1,
                         forecast_mw=prediction, actual_mw=None))
    if not rows or manifest.get('rows', len(rows)) != len(rows):
        raise ValueError('Empty forecast or incorrect row count')
    actuals = {}
    targets = {row['timestamp_utc'] for row in rows}
    observed_at = parse_time(score['scored_at_utc']) if score and score.get('scored_at_utc') else None
    for row in (score or {}).get('rows', []):
        target = timestamp(parse_time(row['timestamp_utc']))
        actual = float(row['actual_mw'])
        if target in actuals or target not in targets or not math.isfinite(actual) or actual <= 0:
            raise ValueError('Duplicate, unrelated or invalid scored observation')
        if observed_at and parse_time(target)+timedelta(hours=1) > observed_at:
            raise ValueError('Actual demand scored before its hour ended')
        actuals[target] = actual
    for row in rows:
        row['actual_mw'] = actuals.get(row['timestamp_utc'])
    scored = [r for r in rows if r['actual_mw'] is not None]
    return dict(id=manifest['forecast_id'], issue_time_utc=manifest['issue_time_utc'],
                origin_utc=manifest['forecast_origin_utc'], rows=rows, metrics=metrics(scored),
                status='complete' if len(scored)==len(rows) else 'partial' if scored else 'pending',
                scored_hours=len(scored), pending_hours=len(rows)-len(scored),
                scored_at_utc=(score or {}).get('scored_at_utc'),
                model_sha256=manifest['model_sha256'], image_uri=manifest.get('image_uri'))


def export(session, limit, max_manifests=500):
    if not 1 <= limit <= 100 or max_manifests < 1:
        raise ValueError('Export needs a limit of 1–100 and a positive manifest allowance')
    s3 = session.client('s3', config=Config(connect_timeout=10, read_timeout=30,
                                          retries={'mode':'standard','total_max_attempts':3}))
    keys = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix='forecasts/runs/'):
        keys.extend(o['Key'] for o in page.get('Contents', []) if o['Key'].endswith('/manifest.json'))
        if len(keys) > max_manifests:
            raise ValueError('Manifest allowance exceeded; review archive size before increasing --max-manifests')
    # Sort by actual issue time, never UUID/execution-name order.
    manifests = sorted((read(s3, k) for k in keys), key=lambda m:parse_time(m['issue_time_utc']), reverse=True)[:limit]
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


def write_snapshot(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.snapshot-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, allow_nan=False)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('dashboard/snapshot.json'))
    parser.add_argument('--profile',default='default')
    parser.add_argument('--limit',type=int,default=30)
    parser.add_argument('--max-manifests',type=int,default=500)
    args=parser.parse_args()
    if not 1<=args.limit<=100: parser.error('limit must be 1–100')
    if args.max_manifests < 1: parser.error('max-manifests must be positive')
    payload=export(boto3.Session(profile_name=args.profile,region_name='us-east-2'),args.limit,args.max_manifests)
    write_snapshot(args.output,payload)
    print(f"Exported {len(payload['runs'])} forecast issues to {args.output}")


if __name__=='__main__': main()
