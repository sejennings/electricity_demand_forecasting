"""Publish an allowlisted dashboard summary without exposing the data lake."""
import json
import os

import boto3
from botocore.config import Config
from gridcast.dashboard import export


def public_snapshot(snapshot):
    run_fields = ('id', 'issue_time_utc', 'origin_utc', 'metrics', 'status',
                  'scored_hours', 'pending_hours', 'scored_at_utc', 'model_sha256')
    row_fields = ('timestamp_utc', 'horizon_hours', 'forecast_mw', 'actual_mw')
    return {
        'generated_at_utc': snapshot['generated_at_utc'],
        'demo': False, 'region': 'DUK', 'public': True,
        'runs': [dict({key: run[key] for key in run_fields},
                      rows=[{key: row[key] for key in row_fields} for row in run['rows']])
                 for run in snapshot['runs']],
        'pipelines': [dict(name=pipeline['name'], executions=[
            {key: execution[key] for key in ('status', 'started_at_utc')}
            for execution in pipeline['executions']]) for pipeline in snapshot['pipelines']],
    }


def handler(event, context):
    session = boto3.Session(region_name='us-east-2')
    payload = public_snapshot(export(session, limit=30, max_manifests=500))
    if not payload['runs']:
        raise ValueError('No forecast issues; keeping the previous public snapshot')
    body = json.dumps(payload, allow_nan=False, separators=(',', ':')).encode()
    if len(body) > 1024 * 1024:
        raise ValueError('Public snapshot exceeds the 1 MiB allowance')
    s3 = session.client('s3', config=Config(connect_timeout=5, read_timeout=20,
                       retries={'mode': 'standard', 'total_max_attempts': 3}))
    s3.put_object(Bucket=os.environ['PUBLIC_BUCKET'], Key='snapshot.json', Body=body,
                  ContentType='application/json', CacheControl='public,max-age=300',
                  ServerSideEncryption='AES256')
    return {'issues': len(payload['runs']), 'generated_at_utc': payload['generated_at_utc']}
