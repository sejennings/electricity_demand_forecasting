"""Reproduce the October 18, 2026 GridCast planning estimate without credits.

Rates are USD for Ohio. Recheck pricing when changing architecture. Storage,
query volume and log volume below are planning allowances, not enforced quotas.
"""
from decimal import Decimal as D
import json


def estimate():
    # 31 daily forecasts plus ten deployment smoke forecasts; no always-on task.
    hourly = D('.5') * D('.04048') + D('2') * D('.004445') + D('.005')
    costs = {
        'forecast_compute_and_ipv4': hourly * D(41) * D(2) / D(60),
        'six_standard_alarms': D('.60'),
        'public_dashboard_publish_and_traffic_allowance': D('1'),
        'one_secret': D('.40'),
        'ecr_5_GiB': D('.50'),
        's3_5_GiB': D('.115'),
        'athena_1000_queries_at_100_MiB': D(1000) * D(100) / D(1024) ** 2 * D(5),
        'logs_1_GB_ingested_and_stored': D('.53'),
        'lambda_workflows_and_requests_allowance': D('1'),
    }
    normal = sum(costs.values())
    stress = normal - costs['forecast_compute_and_ipv4'] + hourly * D(41) * D(40) / D(60)
    return {**costs, 'normal_total': normal, 'stress_total': stress}


if __name__ == '__main__':
    print(json.dumps({key: str(value.quantize(D('.0001'))) for key, value in estimate().items()}, indent=2))
