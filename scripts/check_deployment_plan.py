"""Fail closed on infrastructure deletions; print only addresses and actions."""
import json
from pathlib import Path
import sys

REPLACEABLE = {'aws_ecs_task_definition','aws_lambda_layer_version'}


def superseded_layer_cleanup(plan, resource):
    if resource['type'] != 'aws_lambda_layer_version' or not resource.get('deposed'):
        return False
    old_arn = (resource['change'].get('before') or {}).get('arn')
    def walk(module):
        yield from module.get('resources', [])
        for child in module.get('child_modules', []):
            yield from walk(child)
    root = plan.get('planned_values', {}).get('root_module', {})
    for active in walk(root):
        if active['address'] == resource['address']:
            new_arn = active.get('values', {}).get('arn')
            return bool(old_arn and new_arn and old_arn != new_arn)
    return False


def check(plan):
    if plan.get('errored'):
        raise ValueError('Terraform plan contains errors')
    for resource in plan.get('resource_changes',[]):
        actions=resource['change']['actions']
        replacement = 'create' in actions and resource['type'] in REPLACEABLE
        cleanup = actions == ['delete'] and superseded_layer_cleanup(plan, resource)
        if 'delete' in actions and not (replacement or cleanup):
            raise ValueError(f"Unexpected destruction: {resource['address']}")
        if actions != ['no-op']:
            print(resource['address'],','.join(actions))


def main():
    check(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig')))


if __name__=='__main__':
    main()
