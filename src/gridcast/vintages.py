"""Archived GFS forecasts selected as of issuance, never reanalysis.

Historical public availability is assumed to be initialization + 12 hours;
retrieval time is recorded separately and is NOT historical availability evidence.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import math
from pathlib import Path
from gridcast.baselines import HOUR, instant
from gridcast.ingestion import VARIABLES, cached_request, timestamp, write_csv, write_json

URL = 'https://single-runs-api.open-meteo.com/v1/forecast'
MODEL = 'gfs_seamless'
SCHEMA = 'gfs-weather-v1'
LAG = 12


def weather_features(row):
    values = [float(row[k]) for k in VARIABLES]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Nonfinite weather feature')
    t, rh, rain, wind = values
    if not 0 <= rh <= 100 or rain < 0 or wind < 0:
        raise ValueError('Invalid weather feature range')
    return [*values, max(18-t, 0), max(t-18, 0)]


class Archive:
    def __init__(self, paths):
        self.rows = {}
        self.hashes = {}
        for path in paths:
            path = Path(path)
            self.hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            with path.open(newline='', encoding='utf-8') as stream:
                for row in csv.DictReader(stream):
                    if row['model'] != MODEL or row['availability_basis'] != 'assumed_initialization_plus_12h':
                        raise ValueError('Unsupported weather model or availability policy')
                    run, available, target = map(instant, (row['run_utc'], row['available_at_utc'], row['timestamp_utc']))
                    if available != run + LAG*HOUR or target < run:
                        raise ValueError('Invalid vintage timing')
                    weather_features(row)
                    key = (target, run)
                    if key in self.rows and self.rows[key] != row:
                        raise ValueError('Conflicting weather vintage')
                    self.rows[key] = row
        self.by_target = {}
        for (target, run), row in self.rows.items():
            self.by_target.setdefault(target, []).append((run, row))
        for rows in self.by_target.values():
            rows.sort(key=lambda item: item[0], reverse=True)

    def select(self, issue, target):
        for run, row in self.by_target.get(target, []):
            if instant(row['available_at_utc']) <= issue:
                return row
        return None


def backfill(start, end, output):
    """One prior-day 12 UTC run per daily midnight forecast, end exclusive."""
    if start.hour or end.hour or start < instant('2026-04-03T00:00:00Z') or end > datetime.now(timezone.utc):
        raise ValueError('Use midnight bounds from 2026-04-03 through the present')
    if end <= start:
        raise ValueError('End must follow start')
    rows = []
    issue = start
    while issue < end:
        run = issue-LAG*HOUR
        name = run.strftime('%Y%m%dT%H%M')
        payload = cached_request(output/'raw'/f'{name}.json', URL,
            dict(latitude=35.2271, longitude=-80.8431, models=MODEL,
                 run=run.strftime('%Y-%m-%dT%H:%M'), hourly=','.join(VARIABLES),
                 timezone='GMT', wind_speed_unit='ms', forecast_days=3))
        if payload.get('utc_offset_seconds') != 0:
            raise ValueError('Expected UTC weather')
        expected = dict(zip(VARIABLES, ['°C', '%', 'mm', 'm/s']))
        if any(payload['hourly_units'].get(k) != v for k, v in expected.items()):
            raise ValueError('Unexpected archived-weather units')
        hourly = payload['hourly']
        if any(len(hourly[k]) != len(hourly['time']) for k in VARIABLES):
            raise ValueError('Inconsistent weather arrays')
        daily = []
        for i, t in enumerate(hourly['time']):
            target = instant(timestamp(t))
            if issue <= target < issue+24*HOUR:
                row = dict(timestamp_utc=timestamp(target), run_utc=timestamp(run),
                    available_at_utc=timestamp(issue), model=MODEL,
                    availability_basis='assumed_initialization_plus_12h',
                    **{k:hourly[k][i] for k in VARIABLES})
                weather_features(row)
                daily.append(row)
        if len(daily) != 24 or len({r['timestamp_utc'] for r in daily}) != 24:
            raise ValueError(f'Incomplete vintage for {issue}')
        rows.extend(daily)
        print(f'{issue.date()}: 24 archived forecast hours', flush=True)
        issue += timedelta(days=1)
    path = output/'weather_vintages.csv'
    write_csv(path, rows)
    write_json(output/'manifest.json', dict(model=MODEL, rows=len(rows),
        start_utc=timestamp(start), end_exclusive_utc=timestamp(end),
        retrieved_at_utc=timestamp(datetime.now(timezone.utc)), availability_lag_hours=LAG,
        availability_basis='Assumption, not observed historical publication time',
        source=URL, latitude=35.2271, longitude=-80.8431,
        raw_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (output/'raw').glob('*.json')},
        csv_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', required=True); p.add_argument('--end', required=True)
    p.add_argument('--output', type=Path, default=Path('data/weather-vintages'))
    args = p.parse_args()
    print(backfill(instant(args.start), instant(args.end), args.output))


if __name__ == '__main__':
    main()
