"""Monthly, restartable source imports. All timestamps are UTC."""

import argparse
import csv
import json
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

EIA_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m"]


class SourceRequestError(RuntimeError):
    """Sanitized source failure with explicit transient/permanent classification."""
    def __init__(self, message, *, retryable):
        super().__init__(message)
        self.retryable = retryable


def request_json(url, params, *, timeout=90, attempts=5):
    if attempts < 1 or timeout <= 0:
        raise ValueError('Source requests need positive timeout and attempts')
    host = urlsplit(url).hostname or 'source'
    for attempt in range(attempts):
        try:
            with urlopen(url + "?" + urlencode(params), timeout=timeout) as response:
                payload = json.load(response)
            if payload.get("error"):
                raise ValueError("Source API returned an error; check configuration")
            return payload
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise SourceRequestError(f"{host} request failed (HTTP {exc.code})",
                                         retryable=exc.code in (429, 500, 502, 503, 504)) from None
        except (URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise SourceRequestError(f"{host} request failed after {attempts} attempts ({type(exc).__name__})",
                                         retryable=True) from None
        time.sleep(2 ** attempt)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def cached_request(path, url, params, refresh=False, request_options=None):
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    payload = request_json(url, params, **(request_options or {}))
    # EIA echoes the API key in its request metadata. Never persist that section.
    payload.pop("request", None)
    write_json(path, payload)
    return payload


def month_windows(start, end):
    while start <= end:
        following = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        stop = min(end, following - timedelta(days=1))
        yield start, stop
        start = stop + timedelta(days=1)


def timestamp(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def number(value):
    if value is None or value == "":
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def demand_rows(start, end, region, root, key, refresh=False):
    rows = []
    for first, last in month_windows(start, end):
        offset = 0
        while True:
            params = {"api_key": key, "frequency": "hourly", "data[0]": "value",
                      "facets[respondent][]": region, "facets[type][]": "D",
                      "start": f"{first}T00", "end": f"{last}T23",
                      "sort[0][column]": "period", "sort[0][direction]": "asc",
                      "offset": offset, "length": 5000}
            path = root / "raw/eia" / region / f"{first}_{last}_{offset}.json"
            response = cached_request(path, EIA_URL, params, refresh)["response"]
            batch = response["data"]
            for record in batch:
                if record["respondent"] != region or record["type"] != "D":
                    raise ValueError("Unexpected EIA series")
                if record.get("value-units") != "megawatthours":
                    raise ValueError("Unexpected EIA demand units")
                # Energy over a one-hour interval is numerically equal to mean MW.
                rows.append({"timestamp_utc": timestamp(record["period"]),
                             "region": region, "demand_mw": number(record["value"])})
            offset += len(batch)
            if offset >= int(response["total"]):
                break
            if not batch:
                raise ValueError("EIA pagination ended before reported total")
    return rows


def weather_rows(start, end, latitude, longitude, root, refresh=False):
    rows = []
    for first, last in month_windows(start, end):
        params = {"latitude": latitude, "longitude": longitude, "start_date": str(first),
                  "end_date": str(last), "hourly": ",".join(VARIABLES),
                  "timezone": "GMT", "wind_speed_unit": "ms", "models": "era5"}
        path = root / "raw/weather" / f"{latitude}_{longitude}" / f"{first}_{last}.json"
        payload = cached_request(path, WEATHER_URL, params, refresh)
        expected_units = dict(zip(VARIABLES, ["°C", "%", "mm", "m/s"]))
        if any(payload["hourly_units"].get(k) != v for k, v in expected_units.items()):
            raise ValueError("Unexpected weather units")
        hourly = payload["hourly"]
        if any(len(hourly[v]) != len(hourly["time"]) for v in VARIABLES):
            raise ValueError("Weather arrays differ in length")
        for i, instant in enumerate(hourly["time"]):
            rows.append({"timestamp_utc": timestamp(instant), "latitude": latitude,
                         "longitude": longitude, "weather_source": "open-meteo-era5",
                         **{v: number(hourly[v][i]) for v in VARIABLES}})
    return rows


def quality(rows, start, end, value_columns):
    expected = {timestamp(datetime.combine(start, datetime.min.time()) + timedelta(hours=h))
                for h in range(((end - start).days + 1) * 24)}
    seen = [row["timestamp_utc"] for row in rows]
    if len(seen) != len(set(seen)):
        raise ValueError("Duplicate source timestamps")
    if set(seen) - expected:
        raise ValueError("Source timestamps outside requested interval")
    return {"rows": len(rows), "expected_hours": len(expected),
            "missing_hours": len(expected - set(seen)),
            "null_values": {v: sum(r[v] is None for r in rows) for v in value_columns}}


def write_csv(path, rows):
    if not rows:
        raise ValueError("Source returned no observations")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row["timestamp_utc"]))
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["all", "demand", "weather"], default="all")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--region", default="DUK")
    parser.add_argument("--latitude", type=float, default=35.2271)
    parser.add_argument("--longitude", type=float, default=-80.8431)
    parser.add_argument("--output", type=Path, default=Path("data"))
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--end must be on or after --start")
    if not (-90 <= args.latitude <= 90 and -180 <= args.longitude <= 180):
        parser.error("Invalid latitude/longitude")
    key = os.environ.get("EIA_API_KEY")
    if args.source in ("all", "demand") and not key:
        parser.error("Set the EIA_API_KEY environment variable to your free EIA API key")
    if not args.region.isalnum():
        parser.error("--region must be an alphanumeric EIA respondent code")
    label = f"{args.start}_{args.end}"
    report = {"imported_at_utc": datetime.now(timezone.utc).isoformat(),
              "start": str(args.start), "end": str(args.end), "region": args.region,
              "latitude": args.latitude, "longitude": args.longitude,
              "weather_use": "historical reanalysis; not forecast-time weather"}
    try:
        if args.source in ("all", "demand"):
            rows = demand_rows(args.start, args.end, args.region, args.output, key, args.refresh)
            report["demand"] = quality(rows, args.start, args.end, ["demand_mw"])
            write_csv(args.output / "processed/demand" / args.region / f"{label}.csv", rows)
        if args.source in ("all", "weather"):
            rows = weather_rows(args.start, args.end, args.latitude, args.longitude,
                                args.output, args.refresh)
            report["weather"] = quality(rows, args.start, args.end, VARIABLES)
            write_csv(args.output / "processed/weather" / f"{args.latitude}_{args.longitude}" / f"{label}.csv", rows)
        write_json(args.output / "reports" / f"{args.source}_{args.region}_{args.latitude}_{args.longitude}_{label}.json", report)
    except (ValueError, RuntimeError, KeyError) as exc:
        parser.exit(1, f"Import failed: {exc}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
