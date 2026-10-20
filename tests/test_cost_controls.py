import unittest
from scripts.check_cost_controls import check_plan, check_attempts, check_image_capacity


class CostControlTests(unittest.TestCase):
    def test_unknown_workflow_requires_exact_audited_source_and_existing_limits(self):
        import json
        from pathlib import Path
        from scripts.check_cost_controls import POLICY
        policy = json.loads(POLICY.read_text())
        address = 'aws_sfn_state_machine.forecast'
        rule = policy['resources'][address]
        definition = {'TimeoutSeconds': rule['workflow_limits']['timeout'],
                      'States': rule['workflow_limits']['states']}
        plan = {'planned_values': {'root_module': {'resources': [{
            'address': address, 'mode': 'managed', 'type': rule['type'], 'values': {}}]}},
            'resource_changes': [{'address': address, 'change': {
                'before': {'definition': json.dumps(definition)}, 'after_unknown': {'definition': True}}}]}
        policy['resources'] = {address: rule}
        check_plan(plan, policy)
        rule['definition_source']['sha256'] = 'unreviewed'
        with self.assertRaisesRegex(ValueError, 'audited source'):
            check_plan(plan, policy)

    def test_blocks_new_services_and_compute_increases(self):
        policy = {'resources': {'task': {'type': 'aws_ecs_task_definition',
                                      'limits': {'cpu': '512', 'memory': '2048'}}}}
        resource = {'address': 'task', 'mode': 'managed', 'type': 'aws_ecs_task_definition',
                    'values': {'cpu': '512', 'memory': '2048'}}
        plan = {'planned_values': {'root_module': {'resources': [resource]}}}
        check_plan(plan, policy)
        resource['values']['cpu'] = '4096'
        with self.assertRaisesRegex(ValueError, 'Cost control changed'):
            check_plan(plan, policy)
        resource['values']['cpu'] = '512'
        plan['planned_values']['root_module']['resources'].append(
            {'address': 'nat', 'mode': 'managed', 'type': 'aws_nat_gateway', 'values': {}})
        with self.assertRaisesRegex(ValueError, 'footprint changed'):
            check_plan(plan, policy)

    def test_reruns_consume_monthly_allowance(self):
        self.assertEqual(check_attempts([{'run_attempt': 9}, {'run_attempt': 1}], 10), 10)
        with self.assertRaisesRegex(ValueError, 'allowance exhausted'):
            check_attempts([{'run_attempt': 9}, {'run_attempt': 2}], 10)

    def test_storage_gate_reserves_room_for_next_image(self):
        policy = {'max_ecr_bytes': 500, 'max_image_bytes': 100}
        check_image_capacity([{'imageSizeInBytes': 400}], policy)
        with self.assertRaisesRegex(ValueError, 'storage allowance'):
            check_image_capacity([{'imageSizeInBytes': 401}], policy)

    def test_blocks_workflow_fanout_and_retry_growth(self):
        import copy
        import json
        definition = {'TimeoutSeconds': 1500, 'States': {'Forecast': {
            'Type': 'Task', 'Resource': 'ecs:runTask.sync', 'TimeoutSeconds': 1200,
            'Retry': [{'MaxAttempts': 1}], 'Parameters': {'Count': 1}}}}
        limits = {'timeout': 1500, 'states': {'Forecast': {
            key: value for key, value in definition['States']['Forecast'].items() if key != 'Parameters'}}}
        policy = {'resources': {'workflow': {'type': 'aws_sfn_state_machine',
                                            'limits': {}, 'workflow_limits': limits}}}
        def check(value):
            check_plan({'planned_values': {'root_module': {'resources': [{
                'address': 'workflow', 'mode': 'managed', 'type': 'aws_sfn_state_machine',
                'values': {'definition': json.dumps(value)}}]}}}, policy)
        check(definition)
        modified = copy.deepcopy(definition)
        modified['States']['Forecast']['Retry'][0]['MaxAttempts'] = 100
        with self.assertRaisesRegex(ValueError, 'retries'):
            check(modified)
        modified = copy.deepcopy(definition)
        modified['States']['Forecast']['Parameters']['Count'] = 100
        with self.assertRaisesRegex(ValueError, 'task count'):
            check(modified)
