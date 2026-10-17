"""Expanding monthly evaluation: 2021–2023 history, 2024 validation, 2025 holdout."""
import hashlib
import json
from pathlib import Path
from datetime import timedelta
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits
from joblib import dump
from gridcast.baselines import HOUR, instant, load_demand, predict, metrics, save_rows
from gridcast.ingestion import timestamp, write_json

DATA = Path('data/processed/demand/DUK/2021-01-01_2025-12-31.csv')
OUT = Path('data/models/research')


def features(data, issue, target, delay=24):
    """Only demand strictly before issue minus the assumed publication delay."""
    cutoff = issue - delay * HOUR
    lags = []
    for period in (24, 48, 168, 336):
        source = target - period * HOUR
        while source >= cutoff:
            source -= period * HOUR
        lags.append(data.get(source))
    recent = [data.get(cutoff - h * HOUR) for h in range(1, 25)]
    if any(v is None for v in lags + recent):
        return None
    angle = 2 * np.pi * target.timetuple().tm_yday / 365.25
    return [target.hour, target.weekday(), target.month, np.sin(angle), np.cos(angle),
            *lags, recent[0], np.mean(recent), min(recent), max(recent)]


def grouped_report(rows):
    result = {}
    for model in sorted({r['model'] for r in rows}):
        selected = [r for r in rows if r['model'] == model]
        peaks = {}
        for row in selected:
            key = row['issue_time_utc']
            if key not in peaks or row['actual_mw'] > peaks[key]['actual_mw']:
                peaks[key] = row
        result[model] = {**metrics(selected), 'peak_hour_mae_mw': metrics(list(peaks.values()))['mae_mw']}
    return result


def main():
    data = load_demand([DATA], 'DUK')
    issues, xs, ys, targets = [], [], [], []
    issue = instant('2021-01-15T00:00:00Z')
    while issue < instant('2026-01-01T00:00:00Z'):
        for h in range(24):
            target = issue + h * HOUR
            x = features(data, issue, target)
            if x is not None and data.get(target) is not None:
                issues.append(issue); xs.append(x); ys.append(data[target]); targets.append(target)
        issue += timedelta(days=1)
    X, y = np.array(xs), np.array(ys)
    all_rows, folds = [], []
    # Fixed parameters; no test-year tuning or random validation split.
    config = dict(max_iter=200, max_leaf_nodes=15, learning_rate=0.05,
                  l2_regularization=10, early_stopping=False, random_state=42)
    with threadpool_limits(limits=2):
        for year in (2024, 2025):
            for month in range(1, 13):
                first = instant(f'{year}-{month:02}-01T00:00:00Z')
                stop = instant(f'{year+1}-01-01T00:00:00Z') if month == 12 else instant(f'{year}-{month+1:02}-01T00:00:00Z')
                cutoff = first - 24 * HOUR
                train = np.array([t < cutoff for t in targets])
                model = HistGradientBoostingRegressor(**config).fit(X[train], y[train])
                indices = [i for i, t in enumerate(issues) if first <= t < stop]
                forecasts = dict(zip(indices, model.predict(X[indices])))
                lookup = {targets[i]: (i, forecasts[i]) for i in indices}
                day, evaluated, skipped = first, 0, 0
                while day < stop:
                    baseline = predict(data, day, 24)
                    if (all(r['forecast_mw'] is not None for r in baseline) and
                        all(day + h * HOUR in lookup for h in range(24))):
                        for r in baseline:
                            r['actual_mw'] = data[instant(r['timestamp_utc'])]
                            r['region'] = 'DUK'
                        all_rows.extend(baseline)
                        for h in range(24):
                            target = day + h * HOUR
                            _, value = lookup[target]
                            all_rows.append(dict(issue_time_utc=timestamp(day), timestamp_utc=timestamp(target),
                                horizon_hours=h+1, model='gradient_boosting', forecast_mw=float(value),
                                actual_mw=data[target], region='DUK'))
                        evaluated += 1
                    else:
                        skipped += 1
                    day += timedelta(days=1)
                folds.append(dict(month=str(first)[:7], training_rows=int(train.sum()),
                    training_cutoff_exclusive=timestamp(cutoff), evaluated_days=evaluated, skipped_days=skipped))
                print(f'{year}-{month:02}: {evaluated} days, {skipped} skipped', flush=True)
        # Fit a separate final artifact, only after evaluation, for future inference.
        final_cutoff = instant('2026-01-01T00:00:00Z') - 24 * HOUR
        final_train = np.array([t < final_cutoff for t in targets])
        model = HistGradientBoostingRegressor(**config).fit(X[final_train], y[final_train])
        OUT.mkdir(parents=True, exist_ok=True)
        dump({'model': model, 'availability_delay_hours': 24, 'region': 'DUK',
              'training_cutoff_exclusive': timestamp(final_cutoff)}, OUT / 'model.joblib')
    report = {'region': 'DUK', 'availability_delay_hours': 24, 'parameters': config,
        'sklearn_version': sklearn.__version__, 'input_sha256': hashlib.sha256(DATA.read_bytes()).hexdigest(),
        'protocol': 'Monthly expanding refits; 2024 validation, 2025 prequential holdout; no tuning on 2025. Revised observations, assumed 24h delay.',
        'weather': 'Excluded: historical reanalysis is unavailable as future forecast input.', 'folds': folds,
        'by_year': {}, 'by_season': {}}
    for year in (2024, 2025):
        report['by_year'][str(year)] = grouped_report([r for r in all_rows if r['timestamp_utc'].startswith(str(year))])
        for season, months in {'winter': (12,1,2), 'spring': (3,4,5), 'summer': (6,7,8), 'fall': (9,10,11)}.items():
            report['by_season'][f'{year}_{season}'] = grouped_report([r for r in all_rows
                if r['timestamp_utc'].startswith(str(year)) and int(r['timestamp_utc'][5:7]) in months])
    save_rows(OUT / 'predictions.csv', all_rows)
    write_json(OUT / 'metrics.json', report)
    write_json(Path('reports/historical_evaluation.json'), report)
    print(json.dumps(report['by_year'], indent=2))


if __name__ == '__main__':
    main()
