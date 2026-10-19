"""Fail closed on infrastructure deletions; print only addresses and actions."""
import json
from pathlib import Path
import sys

REPLACEABLE = {'aws_ecs_task_definition','aws_lambda_layer_version'}


def check(plan):
    if plan.get('errored'):
        raise ValueError('Terraform plan contains errors')
    for resource in plan.get('resource_changes',[]):
        actions=resource['change']['actions']
        if 'delete' in actions and not ('create' in actions and resource['type'] in REPLACEABLE):
            raise ValueError(f"Unexpected destruction: {resource['address']}")
        if actions != ['no-op']:
            print(resource['address'],','.join(actions))


def main():
    check(json.loads(Path(sys.argv[1]).read_text()))


if __name__=='__main__':
    main()
