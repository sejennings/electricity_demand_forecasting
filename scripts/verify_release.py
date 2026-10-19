"""Run a genuine forecast using the deployed task and verify immutable provenance."""
import argparse
import csv
from datetime import datetime,timezone,timedelta
import hashlib
import io
import json
import math
import time
import boto3
from gridcast.scoring import parse_time,read_json

BUCKET='gridcast-lake-456112636403-us-east-2'
WORKFLOW='arn:aws:states:us-east-2:456112636403:stateMachine:gridcast-forecast'


def verify_manifest(manifest,image_digest,model_sha256,snapshot):
    expected='456112636403.dkr.ecr.us-east-2.amazonaws.com/gridcast-model@'+image_digest
    if manifest['image_uri']!=expected or manifest['model_sha256']!=model_sha256:
        raise ValueError('Deployed image/model differs from the release')
    if hashlib.sha256(manifest['forecast_csv'].encode()).hexdigest()!=manifest['forecast_sha256']:
        raise ValueError('Forecast hash mismatch')
    issue=parse_time(manifest['issue_time_utc'])
    origin=parse_time(manifest['forecast_origin_utc'])
    if parse_time(snapshot['completed_at_utc'])>issue or origin<=issue:
        raise ValueError('Invalid forecast/snapshot timing')
    rows=list(csv.DictReader(io.StringIO(manifest['forecast_csv'])))
    if len(rows)!=24 or manifest['rows']!=24:
        raise ValueError('Expected 24 forecast hours')
    for h,row in enumerate(rows):
        if (parse_time(row['timestamp_utc'])!=origin+timedelta(hours=h) or
            row['issue_time_utc']!=manifest['issue_time_utc'] or int(row['horizon_hours'])!=h+1 or
            not math.isfinite(float(row['forecast_mw'])) or float(row['forecast_mw'])<=0):
            raise ValueError('Invalid hourly forecast')
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--image-digest',required=True)
    parser.add_argument('--model-sha256',required=True)
    args=parser.parse_args()
    session=boto3.Session(region_name='us-east-2')
    client=session.client('stepfunctions'); s3=session.client('s3')
    execution=client.start_execution(stateMachineArn=WORKFLOW,name=args.run_id,input='{}')['executionArn']
    deadline=time.monotonic()+1500
    while time.monotonic()<deadline:
        result=client.describe_execution(executionArn=execution)
        if result['status']!='RUNNING':
            break
        time.sleep(10)
    else:
        client.stop_execution(executionArn=execution,error='DeploymentVerificationTimeout')
        raise TimeoutError('Forecast verification exceeded workflow deadline')
    if result['status']!='SUCCEEDED':
        raise RuntimeError(f"Forecast failed: {result['status']}; inspect {execution}")
    task=json.loads(result['output'])
    if task['Containers'][0].get('ExitCode')!=0:
        raise RuntimeError('Forecast container did not exit successfully')
    key=f'forecasts/runs/{args.run_id}/manifest.json'
    manifest=read_json(s3,BUCKET,key)
    snapshot=read_json(s3,BUCKET,manifest['snapshot_manifest_key'])
    verify_manifest(manifest,args.image_digest,args.model_sha256,snapshot)
    pointer=read_json(s3,BUCKET,f'scores/runs/{args.run_id}/latest.json')
    score=read_json(s3,BUCKET,pointer['score_key'])
    if score['issue_time_utc']!=manifest['issue_time_utc']:
        raise ValueError('Score points to a different forecast issue')
    print(json.dumps(dict(execution_arn=execution,forecast_manifest_key=key,
        issue_time_utc=manifest['issue_time_utc'],hours=24,score_status=score['status']),indent=2))


if __name__=='__main__':
    main()
