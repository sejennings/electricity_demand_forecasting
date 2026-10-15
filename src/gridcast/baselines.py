"""Issue daily UTC forecasts using only observations before the issue cutoff."""

import argparse
import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gridcast.ingestion import timestamp, write_json

HOUR = timedelta(hours=1)
MODELS = ("persistence", "daily_naive", "weekly_naive", "daily_weekly_mean")


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("Demand timestamps and issue times must explicitly specify UTC")
    if result.minute or result.second or result.microsecond:
        raise ValueError("Timestamps must fall on whole hours")
    return result.astimezone(timezone.utc)


def load_demand(paths, region):
    data = {}
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["region"] != region:
                    continue
                hour = instant(row["timestamp_utc"])
                value = float(row["demand_mw"]) if row["demand_mw"] else None
                if value is not None and (not math.isfinite(value) or value < 0):
                    raise ValueError(f"Invalid demand at {hour}")
                if hour in data and data[hour] != value:
                    raise ValueError(f"Conflicting overlapping records at {hour}")
                data[hour] = value
    if not data:
        raise ValueError("No demand records for selected region")
    return data


def predict(data, issue, delay_hours=0):
    if delay_hours < 0:
        raise ValueError("Availability delay cannot be negative")
    cutoff = issue - delay_hours * HOUR

    def seasonal(target, period):
        source = target - period * HOUR
        while source >= cutoff:
            source -= period * HOUR
        return data.get(source)

    rows = []
    for lead in range(24):
        target = issue + lead * HOUR
        daily = seasonal(target, 24)
        weekly = seasonal(target, 168)
        values = (data.get(cutoff - HOUR), daily, weekly,
                  (daily + weekly) / 2 if daily is not None and weekly is not None else None)
        for model, value in zip(MODELS, values):
            rows.append({"issue_time_utc": timestamp(issue), "timestamp_utc": timestamp(target),
                         "horizon_hours": lead + 1, "model": model, "forecast_mw": value})
    return rows


def metrics(rows):
    errors = [r["forecast_mw"] - r["actual_mw"] for r in rows]
    total = sum(abs(r["actual_mw"]) for r in rows)
    return {"hours": len(rows),
            "mae_mw": sum(abs(e) for e in errors) / len(errors) if errors else None,
            "rmse_mw": math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else None,
            "wape_percent": 100 * sum(abs(e) for e in errors) / total if total else None}


def evaluate(data, start, end, delay_hours=0):
    if end < start or start.hour or end.hour:
        raise ValueError("Evaluation bounds must be ordered UTC midnights")
    predictions, report = [], {}
    issue = start
    folds, skipped = 0, 0
    while issue <= end:
        candidates = predict(data, issue, delay_hours)
        for row in candidates:
            row["actual_mw"] = data.get(instant(row["timestamp_utc"]))
        # Compare all models on identical complete daily windows.
        if all(r["forecast_mw"] is not None and r["actual_mw"] is not None for r in candidates):
            predictions.extend(candidates)
            folds += 1
        else:
            skipped += 1
        issue += timedelta(days=1)
    for model in MODELS:
        selected = [r for r in predictions if r["model"] == model]
        peaks = []
        for issue_time in sorted({r["issue_time_utc"] for r in selected}):
            day = [r for r in selected if r["issue_time_utc"] == issue_time]
            peaks.append(max(day, key=lambda r: r["actual_mw"]))
        report[model] = {**metrics(selected), "actual_daily_peak_hour_mae_mw": metrics(peaks)["mae_mw"]}
    return predictions, {"evaluated_days": folds, "skipped_incomplete_days": skipped,
                         "availability_delay_hours": delay_hours, "models": report,
                         "caveat": "Retrospective revised observations; delay is an assumed availability lag, not verified publication timing."}


def save_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["evaluate", "forecast"])
    parser.add_argument("--input", type=Path, default=Path("data/processed/demand/DUK"))
    parser.add_argument("--region", default="DUK")
    parser.add_argument("--start", help="First evaluation issue time, e.g. 2025-01-08T00:00:00Z")
    parser.add_argument("--end", help="Last evaluation issue time (inclusive)")
    parser.add_argument("--issue", help="Forecast issue time in UTC")
    parser.add_argument("--availability-delay-hours", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path("data/models/baselines"))
    args = parser.parse_args()
    try:
        paths = sorted(args.input.glob("*.csv")) if args.input.is_dir() else [args.input]
        data = load_demand(paths, args.region)
        if args.availability_delay_hours < 0:
            raise ValueError("Availability delay cannot be negative")
        if args.command == "evaluate":
            if not args.start or not args.end:
                raise ValueError("Evaluation requires --start and --end")
            rows, report = evaluate(data, instant(args.start), instant(args.end), args.availability_delay_hours)
            if not rows:
                raise ValueError("No complete evaluation days: import at least a week of prior history plus the evaluation period")
            report.update(region=args.region, start=args.start, end=args.end,
                          input_files=[str(p) for p in paths])
            save_rows(args.output / "backtest_predictions.csv", rows)
            write_json(args.output / "metrics.json", report)
            print(json.dumps(report, indent=2))
        else:
            if not args.issue:
                raise ValueError("Forecast requires --issue")
            rows = predict(data, instant(args.issue), args.availability_delay_hours)
            if any(r["forecast_mw"] is None for r in rows):
                raise ValueError("Missing history for one or more models; import the required prior hours")
            for row in rows:
                row.update(region=args.region, availability_delay_hours=args.availability_delay_hours)
            name = instant(args.issue).strftime("%Y%m%dT%H%MZ")
            save_rows(args.output / f"forecast_{args.region}_{name}.csv", rows)
            print(f"Saved 24-hour forecasts for {len(MODELS)} models to {args.output}")
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Baseline run failed: {exc}\n")


if __name__ == "__main__":
    main()
