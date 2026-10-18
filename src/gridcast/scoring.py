"""Score immutable forecast issues against observed demand, retaining revisions."""
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from botocore.exceptions import ClientError
from gridcast.baselines import HOUR, metrics
from gridcast.ingestion import timestamp


def parse_time(value):
    result = datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result.astimezone(timezone.utc)


def score_rows(rows, actuals, observed_at):
    """No invented actuals; incomplete horizons remain explicitly pending/partial."""
    scored = []
    if not rows or len({r['timestamp_utc'] for r in rows}) != len(rows):
        raise ValueError('Empty/duplicate forecast targets')
    issues = {r['issue_time_utc'] for r in rows}
    if len(issues) != 1:
        raise ValueError('Mixed forecast issues')
    issue = parse_time(next(iter(issues)))
    for r in rows:
        target = parse_time(r['timestamp_utc'])
        prediction = float(r['forecast_mw'])
        if target <= issue or not math.isfinite(prediction) or prediction <= 0:
            raise ValueError('Invalid prospective forecast')
        actual = actuals.get(r['timestamp_utc'])
        if actual is None or target+HOUR > observed_at:
            continue
        actual = float(actual)
        if not math.isfinite(actual) or actual <= 0:
            raise ValueError('Invalid actual demand')
        error = prediction-actual
        scored.append(dict(timestamp_utc=r['timestamp_utc'],issue_time_utc=r['issue_time_utc'],
            horizon_hours=int(r['horizon_hours']),forecast_mw=prediction,actual_mw=actual,
            error_mw=error,absolute_error_mw=abs(error),squared_error_mw2=error*error))
    return dict(issue_time_utc=next(iter(issues)),expected_hours=len(rows),scored_hours=len(scored),
        pending_hours=len(rows)-len(scored),status='complete' if len(scored)==len(rows) else 'partial' if scored else 'pending',
        metrics=metrics(scored),by_horizon={str(r['horizon_hours']):metrics([r]) for r in scored},rows=scored)


def read_json(s3,bucket,key):
    with s3.get_object(Bucket=bucket,Key=key)['Body'] as stream:
        return json.loads(stream.read())


def exists(s3,bucket,key):
    # Exact-prefix listing avoids ambiguous 403/404 behavior with scoped ListBucket.
    return any(o['Key']==key for o in s3.list_objects_v2(Bucket=bucket,Prefix=key,MaxKeys=1).get('Contents',[]))


def put_json(s3,bucket,key,value,immutable=False):
    s3.put_object(Bucket=bucket,Key=key,Body=json.dumps(value,sort_keys=True).encode(),
        ContentType='application/json',ServerSideEncryption='AES256',**({'IfNoneMatch':'*'} if immutable else {}))


def advance_latest(s3,bucket,key,revision_key,observed_at):
    """A late-finishing scorer cannot replace a newer observation's pointer."""
    for attempt in range(5):
        condition={'IfNoneMatch':'*'}
        if exists(s3,bucket,key):
            response=s3.get_object(Bucket=bucket,Key=key)
            with response['Body'] as stream:
                current=json.loads(stream.read())
            if parse_time(current['observed_at_utc']) > observed_at:
                return
            condition={'IfMatch':response['ETag']}
        try:
            s3.put_object(Bucket=bucket,Key=key,Body=json.dumps(dict(score_key=revision_key,
                observed_at_utc=timestamp(observed_at))).encode(),ContentType='application/json',
                ServerSideEncryption='AES256',**condition)
            return
        except ClientError as exc:
            if exc.response['Error']['Code'] not in ('PreconditionFailed','ConditionalRequestConflict','412','409') or attempt==4:
                raise


def score_archive(s3,bucket,observed_at,latest_actuals=None,actual_snapshot_id=None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    manifests=[]
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket,Prefix='forecasts/runs/'):
        manifests.extend(o['Key'] for o in page.get('Contents',[]) if o['Key'].endswith('/manifest.json'))
    # Load monthly actuals lazily. Each run is keyed by its own issue, including
    # overlapping target hours; forecasts are never overwritten by a newer issue.
    actuals, months = {}, set()
    result=[]
    for key in sorted(manifests):
        manifest=read_json(s3,bucket,key)
        raw=manifest['forecast_csv'].encode()
        if hashlib.sha256(raw).hexdigest()!=manifest['forecast_sha256']:
            raise ValueError('Forecast content hash mismatch')
        rows=list(csv.DictReader(io.StringIO(raw.decode())))
        for month in {r['timestamp_utc'][:7] for r in rows} - months:
            months.add(month)
            actual_key=f'curated/parquet/hourly_demand/region=DUK/year={month[:4]}/month={month[5:]}/part-00000.parquet'
            if not exists(s3,bucket,actual_key):
                continue
            response=s3.get_object(Bucket=bucket,Key=actual_key)
            with response['Body'] as stream:
                table=pq.read_table(pa.BufferReader(stream.read()))
            for row in table.to_pylist():
                actuals[timestamp(row['timestamp_utc'].replace(tzinfo=timezone.utc))]=row['demand_mw']
        current={**actuals,**(latest_actuals or {})}
        score=score_rows(rows,current,observed_at)
        score.update(forecast_id=manifest['forecast_id'],forecast_manifest_key=key,
            forecast_sha256=manifest['forecast_sha256'],model_sha256=manifest['model_sha256'])
        digest=hashlib.sha256(json.dumps(score,sort_keys=True).encode()).hexdigest()
        revision_key=f"scores/runs/{manifest['forecast_id']}/revisions/{digest}.json"
        # Content-addressed revisions preserve the first observed time and actuals.
        if not exists(s3,bucket,revision_key):
            score.update(scored_at_utc=timestamp(observed_at),actual_snapshot_id=actual_snapshot_id,
                actuals_policy='Latest published demand at scoring time; revisions retained; no imputation')
            try:
                put_json(s3,bucket,revision_key,score,immutable=True)
            except ClientError as exc:
                if exc.response['Error']['Code'] not in ('PreconditionFailed','412'):
                    raise
                # A concurrent scorer committed this same content-addressed revision.
                read_json(s3,bucket,revision_key)
        advance_latest(s3,bucket,f"scores/runs/{manifest['forecast_id']}/latest.json",revision_key,observed_at)
        result.append(dict(forecast_id=manifest['forecast_id'],status=score['status'],scored_hours=score['scored_hours'],score_key=revision_key))
    return result
