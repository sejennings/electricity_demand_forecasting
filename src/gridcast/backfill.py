"""Run the fixed 2021–2025 research backfill using the cached import pipeline."""
import json
from datetime import date
from pathlib import Path
from gridcast import ingestion
from gridcast.bulk import main as demand_backfill


def main():
    root = Path('data')
    start, end = date(2021, 1, 1), date(2025, 12, 31)
    demand_backfill()
    report = {'demand': json.loads((root / 'reports/demand_backfill.json').read_text())}
    rows = ingestion.weather_rows(start, end, 35.2271, -80.8431, root)
    report['weather'] = ingestion.quality(rows, start, end, ingestion.VARIABLES)
    ingestion.write_csv(root / 'processed/weather/35.2271_-80.8431/2021-01-01_2025-12-31.csv', rows)
    ingestion.write_json(root / 'reports/backfill_2021_2025.json', report)
    ingestion.write_json(Path('reports/backfill_quality.json'), report)
    print(report, flush=True)


if __name__ == '__main__':
    main()
