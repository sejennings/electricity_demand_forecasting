"""Run and observe a bounded GridCast historical ingestion workflow."""
import argparse
import json
import time
import uuid
import boto3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--end-date', default='')
    parser.add_argument('--days', type=int, choices=range(1,8), default=1)
    args = parser.parse_args()
    session = boto3.Session(profile_name='default', region_name='us-east-2')
    account = session.client('sts').get_caller_identity()['Account']
    client = session.client('stepfunctions')
    execution = client.start_execution(
        stateMachineArn=f'arn:aws:states:us-east-2:{account}:stateMachine:gridcast-ingestion',
        name=f'manual-{uuid.uuid4().hex}',
        input=json.dumps({'days':args.days,'end_date':args.end_date}))['executionArn']
    print(execution, flush=True)
    for _ in range(190):
        result = client.describe_execution(executionArn=execution)
        if result['status'] != 'RUNNING':
            print(json.dumps({k:result[k] for k in ('status','output','error','cause') if k in result}, indent=2), flush=True)
            if result['status'] != 'SUCCEEDED':
                raise RuntimeError('Cloud workflow did not succeed')
            return
        time.sleep(10)
    raise TimeoutError('Workflow still running; inspect the execution ARN above')


if __name__ == '__main__':
    main()
