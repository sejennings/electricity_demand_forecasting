"""Extract DUK UTC hourly demand from EIA's official public bulk archive."""
import json
import shutil
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request
from datetime import datetime, timezone, date, timedelta
from gridcast.ingestion import write_csv, quality, write_json, timestamp, number

URL = 'https://www.eia.gov/opendata/bulk/EBA.zip'


def main():
    cached_series = Path('data/raw/eia/DUK/bulk_series.json')
    if cached_series.exists():
        export_series(json.loads(cached_series.read_text()))
        return
    archive = Path('data/raw/eia/EBA.zip')
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists() or not zipfile.is_zipfile(archive):
        temporary = archive.with_suffix('.tmp')
        if archive.exists():
            archive.replace(temporary)
        for attempt in range(5):
            offset = temporary.stat().st_size if temporary.exists() else 0
            request = Request(URL, headers={'Range': f'bytes={offset}-'})
            with urlopen(request, timeout=90) as response:
                append = response.status == 206 and offset > 0
                with temporary.open('ab' if append else 'wb') as output:
                    shutil.copyfileobj(response, output)
            if zipfile.is_zipfile(temporary):
                break
        if not zipfile.is_zipfile(temporary):
            raise ValueError('Incomplete bulk download; rerun to resume')
        temporary.replace(archive)
    print('Bulk archive downloaded', flush=True)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            with bundle.open(name) as stream:
                for line in stream:
                    # Avoid parsing unrelated large time series.
                    if b'"EBA.DUK-ALL.D.H"' not in line:
                        continue
                    series = json.loads(line)
                    if series.get('series_id') != 'EBA.DUK-ALL.D.H':
                        continue
                    write_json(Path('data/raw/eia/DUK/bulk_series.json'), series)
                    export_series(series)
                    return
    raise ValueError('DUK UTC hourly demand series not found in archive')


def export_series(series):
    if series['series_id'] != 'EBA.DUK-ALL.D.H' or series.get('units') != 'megawatthours':
        raise ValueError('Unexpected demand series or units')
    rows = []
    for period, value in series['data']:
        hour = datetime.strptime(period.removesuffix('Z'), '%Y%m%dT%H').replace(tzinfo=timezone.utc)
        if 2021 <= hour.year <= 2025:
            rows.append(dict(timestamp_utc=timestamp(hour), region='DUK', demand_mw=number(value)))
    report = quality(rows, date(2021,1,1), date(2025,12,31), ['demand_mw'])
    observed = {r['timestamp_utc'] for r in rows}
    report['missing_timestamps_utc'] = [timestamp(datetime(2021,1,1,tzinfo=timezone.utc) + timedelta(hours=h))
        for h in range(43824) if timestamp(datetime(2021,1,1,tzinfo=timezone.utc) + timedelta(hours=h)) not in observed]
    report.update(source=URL, series_id=series['series_id'], units=series.get('units'),
                  downloaded_at_utc=datetime.now(timezone.utc).isoformat(),
                  nonpositive_values=sum(r['demand_mw'] is not None and r['demand_mw'] <= 0 for r in rows))
    write_csv(Path('data/processed/demand/DUK/2021-01-01_2025-12-31.csv'), rows)
    write_json(Path('data/reports/demand_backfill.json'), report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
