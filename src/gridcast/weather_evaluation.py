"""Fixed monthly expanding weather ablation on identical daily UTC origins."""
import argparse
import hashlib
from datetime import timedelta
from pathlib import Path
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits
from gridcast.baselines import HOUR, instant, load_demand, metrics, save_rows
from gridcast.ingestion import timestamp, write_json
from gridcast.jobs import CONFIG
from gridcast.research import features
from gridcast.vintages import Archive, weather_features


def evaluate(paths, weather_paths, start, end, output):
    data = load_demand(paths, 'DUK')
    archive = Archive(weather_paths)
    records = []
    day = min(data).replace(hour=0)+timedelta(days=14)
    skipped = 0
    while day < end:
        daily = []
        for h in range(24):
            target = day+h*HOUR
            x = features(data,day,target)
            w = archive.select(day,target)
            if x is None or w is None or data.get(target) is None:
                break
            daily.append((day,target,x,weather_features(w),data[target],w['run_utc']))
        if len(daily)==24:
            records.extend(daily)
        elif day >= start:
            skipped += 1
        day += timedelta(days=1)
    rows, folds = [], []
    first = start
    with threadpool_limits(limits=2):
        while first < end:
            stop = min((first.replace(day=28)+timedelta(days=4)).replace(day=1),end)
            cutoff = first-24*HOUR
            training = [r for r in records if r[1] < cutoff]
            testing = [r for r in records if first <= r[0] < stop]
            if len(training)<720 or not testing:
                raise ValueError('Insufficient paired training/evaluation rows')
            for name, weather in [('demand_only',False),('weather_vintage',True)]:
                model = HistGradientBoostingRegressor(**CONFIG)
                vector = lambda r: r[2]+r[3] if weather else r[2]
                model.fit(np.array([vector(r) for r in training]),np.array([r[4] for r in training]))
                values = model.predict([vector(r) for r in testing])
                for r, value in zip(testing,values):
                    rows.append(dict(issue_time_utc=timestamp(r[0]),timestamp_utc=timestamp(r[1]),
                        model=name,actual_mw=r[4],forecast_mw=float(value),weather_run_utc=r[5]))
            folds.append(dict(start=timestamp(first),end_exclusive=timestamp(stop),
                training_cutoff_exclusive=timestamp(cutoff),training_rows=len(training),test_rows=len(testing)))
            first = stop
    report = dict(protocol='Fixed parameters, monthly expanding refits, identical paired samples, daily 00 UTC origins; revised demand with assumed 24h delay.',
        weather_availability='Initialization + 12h assumed; actual historical publication timestamps unavailable.',
        limitations='April 2026 onward archive; no winter test. One Charlotte weather point. Live hourly origins differ from daily test origins.',
        start=timestamp(start),end_exclusive=timestamp(end),parameters=CONFIG,folds=folds,
        skipped_test_days=skipped,weather_input_sha256=archive.hashes,
        demand_input_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        overall={name:metrics([r for r in rows if r['model']==name]) for name in ('demand_only','weather_vintage')},
        by_month={f['start'][:7]:{name:metrics([r for r in rows if r['model']==name and r['timestamp_utc'].startswith(f['start'][:7])])
            for name in ('demand_only','weather_vintage')} for f in folds})
    save_rows(output/'predictions.csv', rows)
    write_json(output/'metrics.json', report)
    return report


def main():
    import json
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,nargs='+',required=True)
    p.add_argument('--weather-vintages',type=Path,nargs='+',required=True)
    p.add_argument('--start',required=True); p.add_argument('--end',required=True)
    p.add_argument('--output',type=Path,default=Path('data/models/weather-evaluation'))
    args = p.parse_args()
    start,end = instant(args.start),instant(args.end)
    if start.day != 1 or start.hour or end.hour or end <= start:
        p.error('Start must be the first day of a month at midnight; end must follow start')
    print(json.dumps(evaluate(args.input,args.weather_vintages,start,end,args.output)['overall'],indent=2))


if __name__ == '__main__':
    main()
