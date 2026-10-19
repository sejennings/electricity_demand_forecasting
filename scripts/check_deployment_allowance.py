"""Fail closed before AWS authentication after ten monthly release attempts."""
from datetime import datetime, timezone
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from scripts.check_cost_controls import POLICY, check_attempts


def main():
    month = datetime.now(timezone.utc).strftime('%Y-%m-01')
    repository = os.environ['GITHUB_REPOSITORY']
    runs = []
    for page in range(1, 102):
        query = urlencode({'branch': 'main', 'created': '>=' + month, 'per_page': 100, 'page': page})
        request = Request(f'https://api.github.com/repos/{repository}/actions/workflows/deploy.yml/runs?{query}',
                          headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                                   'Accept': 'application/vnd.github+json'})
        with urlopen(request, timeout=30) as response:
            batch = json.load(response)['workflow_runs']
        runs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError('Incomplete deployment history; refusing AWS access')
    if not any(str(run['id']) == os.environ['GITHUB_RUN_ID'] for run in runs):
        raise ValueError('Current run missing from history; refusing AWS access')
    attempts = check_attempts(runs, json.loads(POLICY.read_text())['max_deployment_attempts_per_month'])
    print(f'Monthly release attempts: {attempts}/10 (including failures and reruns)')


if __name__ == '__main__':
    main()
