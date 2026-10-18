"""Immutable collection-time snapshots of recent demand and current weather forecasts."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import uuid
from gridcast.ingestion import EIA_URL, VARIABLES, cached_request, number, timestamp, write_csv, write_json
from gridcast.baselines import HOUR, instant

FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'


def now():
    return datetime.now(timezone.utc)


def recent_demand(key, root, as_of):
    end = as_of.replace(minute=0,second=0,microsecond=0) - HOUR
    start = end - timedelta(days=31)
    params = {'api_key':key,'frequency':'hourly','data[0]':'value',
        'facets[respondent][]':'DUK','facets[type][]':'D',
        'sort[0][column]':'period','sort[0][direction]':'desc','offset':0,'length':1000}
    source='eia-api-v2'
    fallback_reason=None
    try:
        payload = cached_request(root/'raw/demand.json',EIA_URL,params,
                                 request_options={'timeout':15,'attempts':1})['response']
    except RuntimeError as exc:
        from gridcast.eia_export import download,read_rows
        fallback_reason=str(exc)
        export=root/'raw/DUK.xlsx'
        download(export)
        exported=read_rows(export,start,end)
        payload={'data':[dict(period=r['timestamp_utc'],respondent='DUK',type='D',
                              value=r['demand_mw'],**{'value-units':'megawatthours'}) for r in exported]}
        latest_params={**params,'length':1}
        try:
            latest=cached_request(root/'raw/demand_latest.json',EIA_URL,latest_params,
                                  request_options={'timeout':15,'attempts':2})['response']['data']
        except RuntimeError:
            # The official workbook is independently published actual demand.
            # A second API outage must not discard that valid source; gaps stay visible.
            latest=[]
            fallback_reason += '; latest-hour API unavailable; using published export only'
        # The API's latest observed hour supplements the official export; it does not
        # fill any unavailable hours between the export and API publication times.
        by_time={timestamp(r['period']):r for r in payload['data']}
        by_time.update({timestamp(r['period']):r for r in latest})
        payload['data']=list(by_time.values())
        source='eia-published-hourly-export-plus-latest-api' if latest else 'eia-published-hourly-export'
    # A bounded reverse scan avoids a slow EIA date-range query. Total describes all
    # history, so intentional truncation is expected. Enforce the as-of window locally.
    if len(payload['data']) > 1000:
        raise ValueError('Unexpectedly large recent demand response')
    rows = []
    for record in payload['data']:
        if record['respondent'] != 'DUK' or record['type'] != 'D' or record['value-units'] != 'megawatthours':
            raise ValueError('Unexpected demand series/units')
        ts = timestamp(record['period'])
        if not start <= instant(ts) <= end:
            continue
        value = number(record['value'])
        if value is not None and value <= 0:
            raise ValueError('Nonpositive recent demand')
        rows.append(dict(timestamp_utc=ts,region='DUK',demand_mw=value))
    if len({r['timestamp_utc'] for r in rows}) != len(rows):
        raise ValueError('Duplicate recent demand timestamps')
    valid = [r for r in rows if r['demand_mw'] is not None]
    if not valid:
        raise ValueError('No recent demand observations available')
    latest = max(r['timestamp_utc'] for r in valid)
    return rows, dict(request_start_utc=timestamp(start),request_end_utc=timestamp(end),
        latest_observation_utc=latest,expected_hours=int((end-start)/HOUR)+1,
        missing_hours=int((end-start)/HOUR)+1-len(rows),null_hours=len(rows)-len(valid),
        observation_lag_hours=(as_of-instant(latest))/HOUR,available_at_utc=timestamp(now()),
        retrieval_source=source,fallback_reason=fallback_reason)


def forecast_weather(root):
    payload = cached_request(root/'raw/weather_forecast.json',FORECAST_URL,
        {'latitude':35.2271,'longitude':-80.8431,'hourly':','.join(VARIABLES),
         'timezone':'GMT','wind_speed_unit':'ms','models':'gfs_seamless','forecast_days':4},
        request_options={'timeout':30,'attempts':3})
    available = timestamp(now())
    expected_units = dict(zip(VARIABLES,['°C','%','mm','m/s']))
    if any(payload['hourly_units'].get(k) != v for k,v in expected_units.items()):
        raise ValueError('Unexpected forecast-weather units')
    hourly = payload['hourly']
    if any(len(hourly[k]) != len(hourly['time']) for k in VARIABLES):
        raise ValueError('Forecast weather arrays differ in length')
    rows = [dict(timestamp_utc=timestamp(t), available_at_utc=available,
                 latitude=35.2271,longitude=-80.8431,weather_source='open-meteo-gfs-seamless',
                 **{k:number(hourly[k][i]) for k in VARIABLES}) for i,t in enumerate(hourly['time'])]
    if len({r['timestamp_utc'] for r in rows}) != len(rows):
        raise ValueError('Duplicate forecast weather timestamps')
    if not rows or any(r[k] is None for r in rows for k in VARIABLES):
        raise ValueError('Missing forecast weather values')
    return rows,dict(available_at_utc=available,model_requested='gfs_seamless',
        provider_model_initialization_utc=None,
        timing_note='Availability is measured at response retrieval; provider initialization time is not supplied.')


def collect(key, output):
    started = now()
    snapshot_id = started.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:12]
    root = Path(output)/'snapshots'/snapshot_id
    root.mkdir(parents=True,exist_ok=False)
    demand, demand_report = recent_demand(key,root,started)
    weather, weather_report = forecast_weather(root)
    write_csv(root/'demand.csv',demand)
    write_csv(root/'weather_forecast.csv',weather)
    manifest = dict(snapshot_id=snapshot_id,collection_started_at_utc=timestamp(started),
        completed_at_utc=timestamp(now()),region='DUK',demand=demand_report,weather=weather_report,
        demand_file='demand.csv',weather_file='weather_forecast.csv',demand_rows=len(demand),weather_rows=len(weather))
    write_json(root/'manifest.json',manifest)
    write_json(Path(output)/'latest.json',{'snapshot_manifest':f'snapshots/{snapshot_id}/manifest.json'})
    return root,manifest


def upload(s3,bucket,root,manifest):
    snapshot_id = manifest['snapshot_id']
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        prefix = 'raw' if relative.startswith('raw/') else 'processed'
        if relative.endswith('.xlsx'):
            prefix='raw/operational-export'
            key=f'{prefix}/snapshot={snapshot_id}/DUK.xlsx'
            s3.upload_file(str(path),bucket,key,ExtraArgs={'ServerSideEncryption':'AES256'})
            continue
        key = f'{prefix}/operational/snapshot={snapshot_id}/{relative}'
        s3.upload_file(str(path),bucket,key,ExtraArgs={'ServerSideEncryption':'AES256'})
    key = f'reports/operational/snapshot={snapshot_id}.json'
    s3.put_object(Bucket=bucket,Key=key,Body=json.dumps(manifest).encode(),
                  ContentType='application/json',ServerSideEncryption='AES256')
    return key
