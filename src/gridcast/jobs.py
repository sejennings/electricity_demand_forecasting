"""Container entry points for live imports, model training, and future forecasts."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid
from joblib import dump,load
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits
from gridcast.baselines import HOUR,instant,load_demand,save_rows
from gridcast.ingestion import timestamp,write_json
from gridcast.research import features

CONFIG = dict(max_iter=200,max_leaf_nodes=15,learning_rate=0.05,l2_regularization=10,
              early_stopping=False,random_state=42)


def train(paths,cutoff,output,weather_paths=None):
    from gridcast.vintages import Archive, SCHEMA, MODEL, weather_features
    archive = Archive(weather_paths) if weather_paths else None
    data = load_demand(paths,'DUK')
    X,y = [],[]
    issue = min(data).replace(hour=0)+timedelta(days=14)
    while issue < cutoff:
        for h in range(24):
            target = issue+h*HOUR
            if target >= cutoff or data.get(target) is None:
                continue
            x = features(data,issue,target,24)
            if x is not None and archive is not None:
                weather = archive.select(issue,target)
                x = x+weather_features(weather) if weather else None
            if x is not None:
                X.append(x); y.append(data[target])
        issue += timedelta(days=1)
    if len(y) < 24*30:
        raise ValueError('Training requires at least 30 days of usable labeled hours')
    with threadpool_limits(limits=2):
        model = HistGradientBoostingRegressor(**CONFIG).fit(np.array(X),np.array(y))
    metadata = dict(region='DUK',availability_delay_hours=24,training_cutoff_exclusive=timestamp(cutoff),
        trained_at_utc=timestamp(datetime.now(timezone.utc)),training_rows=len(y),uses_weather=archive is not None,
        parameters=CONFIG,input_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    if archive is not None:
        metadata.update(weather_schema=SCHEMA,weather_model=MODEL,weather_input_sha256=archive.hashes,
            weather_availability_lag_hours=12,weather_availability_basis='assumed_initialization_plus_12h')
    output.parent.mkdir(parents=True,exist_ok=True)
    dump({'model':model,**metadata},output)
    write_json(output.with_suffix('.json'),metadata)
    return metadata


def forecast(model_path,manifest_path,output,issued=None):
    issued = issued or datetime.now(timezone.utc)
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if 'snapshot_manifest' in manifest:
        pointer = Path(manifest['snapshot_manifest'])
        manifest_path = pointer if pointer.is_absolute() else manifest_path.parent/pointer
        manifest = json.loads(manifest_path.read_text())
    available = datetime.fromisoformat(manifest['completed_at_utc'].replace('Z','+00:00'))
    if available > issued:
        raise ValueError('Snapshot was not available at forecast issuance')
    origin = issued.replace(minute=0,second=0,microsecond=0)+HOUR
    artifact = load(model_path)  # Only load trusted model artifacts.
    cutoff = origin-artifact['availability_delay_hours']*HOUR
    if instant(artifact['training_cutoff_exclusive']) > min(cutoff,issued):
        raise ValueError('Model training includes labels unavailable at forecast origin')
    uses_weather = artifact.get('uses_weather',False)
    if uses_weather:
        from gridcast.vintages import SCHEMA, MODEL, weather_features
        if artifact.get('weather_schema') != SCHEMA or artifact.get('weather_model') != MODEL:
            raise ValueError('Unsupported weather model/feature schema')
        if manifest.get('weather',{}).get('model_requested') != MODEL:
            raise ValueError('Snapshot weather model differs from training')
    data = load_demand([manifest_path.parent/manifest['demand_file']],artifact['region'])
    with (manifest_path.parent/manifest['weather_file']).open(newline='',encoding='utf-8') as stream:
        weather = {r['timestamp_utc']:r for r in csv.DictReader(stream)}
    X, rows = [],[]
    for h in range(24):
        target = origin+h*HOUR
        x = features(data,origin,target,artifact['availability_delay_hours'])
        if x is None:
            raise ValueError(f'Missing required demand history for {timestamp(target)}; no values were filled')
        w = weather.get(timestamp(target))
        if not w or datetime.fromisoformat(w['available_at_utc'].replace('Z','+00:00')) > issued:
            raise ValueError('Forecast weather was not available for the full target horizon at issuance')
        if uses_weather:
            x += weather_features(w)
        X.append(x)
        rows.append(dict(issue_time_utc=timestamp(issued),forecast_origin_utc=timestamp(origin),
            timestamp_utc=timestamp(target),horizon_hours=h+1,region=artifact['region'],
            forecast_mw=None,weather_forecast_temp_c=float(w['temperature_2m']),
            weather_used_by_model=uses_weather,snapshot_id=manifest['snapshot_id']))
    with threadpool_limits(limits=2):
        values=artifact['model'].predict(X)
    for row,value in zip(rows,values):
        row['forecast_mw']=float(value)
    output.mkdir(parents=True,exist_ok=True)
    name=issued.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:12]
    path=output/f'forecast_{name}.csv'
    save_rows(path,rows)
    write_json(path.with_suffix('.json'),dict(issue_time_utc=timestamp(issued),forecast_origin_utc=timestamp(origin),
        snapshot_id=manifest['snapshot_id'],model_sha256=hashlib.sha256(Path(model_path).read_bytes()).hexdigest(),
        uses_weather=uses_weather,rows=24,feature_cutoff_exclusive_utc=timestamp(cutoff)))
    return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('import-live')
    p.add_argument('--output',type=Path,default=Path('data/operational'))
    p.add_argument('--profile'); p.add_argument('--bucket')
    p.add_argument('--secret-id',default='gridcast/eia-api-key')
    p=commands.add_parser('train')
    p.add_argument('--input',type=Path,nargs='+',required=True)
    p.add_argument('--cutoff',required=True)
    p.add_argument('--weather-vintages',type=Path,nargs='+',help='Archived forecast CSVs with as-of timing')
    p.add_argument('--output',type=Path,default=Path('data/models/container/model.joblib'))
    p=commands.add_parser('forecast')
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('data/forecasts'))
    args=parser.parse_args()
    if args.command=='import-live':
        import boto3
        from gridcast.live import collect,upload
        session=boto3.Session(profile_name=args.profile,region_name='us-east-2')
        key=os.environ.get('EIA_API_KEY')
        if not key:
            key=session.client('secretsmanager').get_secret_value(SecretId=args.secret_id)['SecretString']
        root,manifest=collect(key,args.output)
        if args.bucket:
            upload(session.client('s3'),args.bucket,root,manifest)
        print(json.dumps(manifest,indent=2))
    elif args.command=='train':
        cutoff=instant(args.cutoff)
        if cutoff>datetime.now(timezone.utc):
            parser.error('Training cutoff cannot be in the future')
        print(json.dumps(train(args.input,cutoff,args.output,args.weather_vintages),indent=2))
    else:
        print(forecast(args.model,args.snapshot,args.output))


if __name__=='__main__':
    main()
