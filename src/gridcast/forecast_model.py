"""Generate 24-hour demand forecasts from a trusted locally trained artifact."""
import argparse
from pathlib import Path
from joblib import load
from gridcast.baselines import HOUR, instant, load_demand, save_rows
from gridcast.research import features
from gridcast.ingestion import timestamp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--issue', required=True)
    parser.add_argument('--model', type=Path, default=Path('data/models/research/model.joblib'))
    parser.add_argument('--input', type=Path, default=Path('data/processed/demand/DUK/2021-01-01_2025-12-31.csv'))
    parser.add_argument('--output', type=Path, default=Path('data/models/research'))
    args = parser.parse_args()
    artifact = load(args.model)  # Load only trusted local artifacts; joblib is executable serialization.
    issue = instant(args.issue)
    cutoff = issue - artifact['availability_delay_hours'] * HOUR
    if instant(artifact['training_cutoff_exclusive']) > cutoff:
        parser.error('Model was trained on labels unavailable at the requested issue time')
    data = load_demand([args.input], artifact['region'])
    X = [features(data, issue, issue+h*HOUR, artifact['availability_delay_hours']) for h in range(24)]
    if any(x is None for x in X):
        parser.error('Missing required history at the requested issue time')
    values = artifact['model'].predict(X)
    rows = [dict(issue_time_utc=timestamp(issue), timestamp_utc=timestamp(issue+h*HOUR),
                 region=artifact['region'], horizon_hours=h+1, model='gradient_boosting',
                 forecast_mw=float(v), availability_delay_hours=artifact['availability_delay_hours'])
            for h,v in enumerate(values)]
    output = args.output / f"forecast_{issue.strftime('%Y%m%dT%H%MZ')}.csv"
    save_rows(output, rows)
    print(output)


if __name__ == '__main__':
    main()
