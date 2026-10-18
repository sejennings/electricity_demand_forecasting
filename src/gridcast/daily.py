"""Daily Fargate inference with immutable S3 issue records and delayed scoring."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import boto3
from botocore.config import Config
from gridcast.ingestion import timestamp
from gridcast.scoring import read_json, put_json, score_archive, exists, parse_time


def run(s3,secrets,bucket,model_key,model_hash,run_id):
    from gridcast.jobs import forecast
    from gridcast.live import collect,upload
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',run_id):
        raise ValueError('Invalid run id')
    manifest_key=f'forecasts/runs/{run_id}/manifest.json'
    existing=read_json(s3,bucket,manifest_key) if exists(s3,bucket,manifest_key) else None
    with tempfile.TemporaryDirectory() as temporary:
        folder=Path(temporary)
        key=secrets.get_secret_value(SecretId=os.environ['EIA_SECRET_ARN'])['SecretString']
        root,snapshot=collect(key,folder/'inputs')
        upload(s3,bucket,root,snapshot)
        with (root/'demand.csv').open(newline='') as stream:
            actuals={r['timestamp_utc']:float(r['demand_mw']) for r in csv.DictReader(stream) if r['demand_mw']}
        if existing is None:
            model=folder/'model.joblib'
            s3.download_file(bucket,model_key,str(model))
            if hashlib.sha256(model.read_bytes()).hexdigest()!=model_hash:
                raise ValueError('Model hash mismatch; refusing to load')
            # Issue time is captured after inputs are available, never the scheduled time.
            path=forecast(model,root/'manifest.json',folder/'forecasts')
            meta=json.loads(path.with_suffix('.json').read_text())
            if parse_time(meta['forecast_origin_utc']) <= datetime.now(timezone.utc):
                raise ValueError('Forecast origin elapsed before publication')
            raw=path.read_bytes()
            existing=dict(**meta,forecast_id=run_id,forecast_csv=raw.decode(),
                forecast_sha256=hashlib.sha256(raw).hexdigest(),model_key=model_key,
                image_uri=os.environ.get('MODEL_IMAGE_URI'),published_at_utc=timestamp(datetime.now(timezone.utc)),
                snapshot_manifest_key=f"reports/operational/snapshot={snapshot['snapshot_id']}.json")
            put_json(s3,bucket,manifest_key,existing,immutable=True)
        scores=score_archive(s3,bucket,datetime.now(timezone.utc),actuals,snapshot['snapshot_id'])
        result=dict(forecast_id=run_id,manifest_key=manifest_key,issue_time_utc=existing['issue_time_utc'],
            forecast_rows=existing['rows'],scores=scores)
        print(json.dumps(result),flush=True)
        return result


def main():
    session=boto3.Session(region_name='us-east-2')
    config=Config(retries={'mode':'standard','total_max_attempts':4},connect_timeout=10,read_timeout=60)
    run(session.client('s3',config=config),session.client('secretsmanager',config=config),
        os.environ['LAKE_BUCKET'],os.environ['MODEL_KEY'],os.environ['MODEL_SHA256'],os.environ['RUN_ID'])


if __name__=='__main__':
    main()
