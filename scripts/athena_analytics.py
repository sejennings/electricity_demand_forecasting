"""Install reporting views and capture bounded Athena CLI query validation results."""
import json
from pathlib import Path
import shutil
import subprocess
import time
from gridcast.ingestion import write_json


def aws(*args):
    executable = shutil.which('aws') or str(Path.home()/'AppData/Local/Programs/Amazon/AWSCLIV2/aws.exe')
    result = subprocess.run([executable,'athena',*args,'--profile','default','--region','us-east-2',
                             '--no-cli-pager','--output','json'],check=True,capture_output=True,encoding='utf-8')
    return json.loads(result.stdout)


def query(sql):
    execution = aws('start-query-execution','--work-group','gridcast-analytics',
                    '--query-execution-context','Database=gridcast,Catalog=AwsDataCatalog',
                    '--query-string',sql)['QueryExecutionId']
    for _ in range(120):
        result = aws('get-query-execution','--query-execution-id',execution)['QueryExecution']
        if result['Status']['State'] in ('FAILED','CANCELLED'):
            raise RuntimeError(result['Status'])
        if result['Status']['State'] == 'SUCCEEDED':
            values = aws('get-query-results','--query-execution-id',execution)
            return dict(query_id=execution,bytes_scanned=result.get('Statistics',{}).get('DataScannedInBytes',0),
                runtime_ms=result.get('Statistics',{}).get('TotalExecutionTimeInMillis',0),
                rows=[[v.get('VarCharValue') for v in row['Data']] for row in values['ResultSet']['Rows']])
        time.sleep(2)
    raise TimeoutError(execution)


def main():
    for path in sorted(Path('sql/views').glob('*.sql')):
        query(path.read_text())
        print(f'Installed {path.stem}',flush=True)
    results = {}
    # Profile timestamp/type compatibility and required values before report queries.
    results['sample'] = query("SELECT * FROM gridcast.hourly_demand_weather WHERE region='DUK' AND year='2025' AND month='01' ORDER BY timestamp_utc LIMIT 5")
    results['source_counts'] = query("SELECT 'demand' AS source,count(*) AS row_count FROM gridcast.hourly_demand WHERE region='DUK' AND year BETWEEN '2021' AND '2025' UNION ALL SELECT 'weather',count(*) FROM gridcast.hourly_weather WHERE region='DUK' AND year BETWEEN '2021' AND '2025'")
    for path in sorted(Path('sql/reports').glob('*.sql')):
        results[path.stem] = query(path.read_text())
        print(f'{path.stem}: {results[path.stem]["bytes_scanned"]} bytes scanned',flush=True)
    count_rows = {r[0]:int(r[1]) for r in results['source_counts']['rows'][1:]}
    if count_rows != {'demand':43823,'weather':43824}:
        raise ValueError(f'Historical source count mismatch: {count_rows}')
    validation = results['validation']['rows'][1]
    if validation[:3] != ['43823','43823','0']:
        raise ValueError(f'Joined count/duplicates/null validation failed: {validation}')
    missing = results['missing_hours']['rows'][1:]
    if len(missing) != 1 or missing[0][1] != '2025-11-03' or missing[0][7:10] != ['1','0','0']:
        # Keep the raw result for inspection even when a validation expectation fails.
        write_json(Path('reports/athena_validation.json'),results)
        raise ValueError(f'Unexpected completeness report: {missing}')
    write_json(Path('reports/athena_validation.json'),results)
    print('Historical row counts, null checks, uniqueness and missing-hour checks passed.',flush=True)


if __name__ == '__main__':
    main()
