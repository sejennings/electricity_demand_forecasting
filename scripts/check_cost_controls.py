"""Enforce the audited footprint; these controls are not a billing cap."""
import json
import hashlib
from decimal import Decimal
from pathlib import Path

POLICY = Path(__file__).resolve().parents[1] / 'infrastructure/cost-controls.json'


def check_plan(plan, policy=None):
    policy = policy or json.loads(POLICY.read_text())
    expected = policy['resources']
    def walk(module):
        yield from module.get('resources', [])
        for child in module.get('child_modules', []):
            yield from walk(child)
    resources = {r['address']: r for r in walk(plan['planned_values']['root_module'])
                 if r.get('mode') == 'managed'}
    if resources.keys() != expected.keys():
        raise ValueError('Infrastructure footprint changed; review the cost estimate and policy first')
    for address, resource in resources.items():
        rule = expected[address]
        if resource['type'] != rule['type']:
            raise ValueError(f'Unreviewed resource type: {address}')
        values = resource['values']
        for field, limit in rule['limits'].items():
            actual = (values['configuration'][0].get(field)
                      if field == 'bytes_scanned_cutoff_per_query' else values.get(field))
            if field == 'limit_amount' and actual is not None:
                actual, limit = Decimal(str(actual)), Decimal(str(limit))
            if actual != limit:
                raise ValueError(f'Cost control changed or unknown: {address}.{field}')
        if 'workflow_limits' in rule:
            source = rule.get('definition_source')
            if source:
                path = POLICY.parents[1] / source['path']
                if not path.is_file() or hashlib.sha256(path.read_text().encode()).hexdigest() != source.get('sha256'):
                    raise ValueError(f'Workflow requires audited source: {address}')
            raw_definition = values.get('definition')
            if raw_definition is None:
                # A new pinned ECS revision makes jsonencode unknown at plan time.
                # Accept only the exact audited HCL, with no variable-driven cost
                # settings, and verify the existing definition's limits as well.
                if not source:
                    raise ValueError(f'Unknown workflow definition requires audited source: {address}')
                change = next((r['change'] for r in plan.get('resource_changes', []) if r['address'] == address), {})
                if change.get('after_unknown', {}).get('definition') is not True:
                    raise ValueError(f'Missing workflow definition: {address}')
                raw_definition = (change.get('before') or {}).get('definition')
                if raw_definition is None:
                    raise ValueError(f'No audited existing workflow: {address}')
            definition = json.loads(raw_definition)
            shape = {'timeout': definition.get('TimeoutSeconds'), 'states': {
                name: {key: state[key] for key in ['Type', 'Resource', 'TimeoutSeconds', 'Retry'] if key in state}
                for name, state in definition['States'].items()}}
            if shape != rule['workflow_limits']:
                raise ValueError(f'Workflow tasks, retries or deadlines changed: {address}')
            for state in definition['States'].values():
                parameters = state.get('Parameters', {})
                if parameters.get('Count', 1) != 1 or set(parameters.get('Overrides', {})) - {'ContainerOverrides'}:
                    raise ValueError(f'Unreviewed ECS task count or compute override: {address}')
                for container in parameters.get('Overrides', {}).get('ContainerOverrides', []):
                    if set(container) - {'Name', 'Environment'}:
                        raise ValueError(f'Unreviewed ECS container override: {address}')


def check_attempts(runs, limit):
    attempts = sum(run['run_attempt'] for run in runs)
    if attempts > limit:
        raise ValueError(f'Monthly deployment allowance exhausted ({attempts}/{limit}); no AWS changes allowed')
    return attempts


def check_image_capacity(images, policy):
    stored = sum(image['imageSizeInBytes'] for image in images)
    if stored + policy['max_image_bytes'] > policy['max_ecr_bytes']:
        raise ValueError('ECR storage allowance reached; review unused images before publishing')


if __name__ == '__main__':
    import sys
    check_plan(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig')))
