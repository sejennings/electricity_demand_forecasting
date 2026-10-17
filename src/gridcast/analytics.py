"""Typed monthly Parquet datasets with optimistic S3 upserts."""
from collections import defaultdict
from datetime import date, datetime, timezone
import json
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

DEMAND = [('timestamp_utc', pa.timestamp('us')), ('demand_mw', pa.float64())]
WEATHER = [('timestamp_utc', pa.timestamp('us')), ('temperature_2m', pa.float64()),
           ('relative_humidity_2m', pa.float64()), ('precipitation', pa.float64()),
           ('wind_speed_10m', pa.float64()), ('latitude', pa.float64()),
           ('longitude', pa.float64()), ('weather_source', pa.string())]
SCHEMAS = {
    'hourly_demand': pa.schema(DEMAND),
    'hourly_weather': pa.schema(WEATHER),
    'hourly_demand_weather': pa.schema(DEMAND + WEATHER[1:]),
    'dim_calendar': pa.schema([('calendar_date',pa.date32()), ('day_of_week',pa.int32()),
        ('is_weekend',pa.bool_()), ('month_number',pa.int32()), ('year_number',pa.int32())]),
    'dim_region': pa.schema([('region',pa.string()), ('region_name',pa.string()),
        ('local_timezone',pa.string()), ('weather_latitude',pa.float64()), ('weather_longitude',pa.float64())]),
}


def normalize(rows, schema):
    result = []
    for row in rows:
        record = {field.name: row.get(field.name) for field in schema}
        if 'timestamp_utc' in record:
            value = record['timestamp_utc']
            if isinstance(value, str):
                value = datetime.fromisoformat(value.replace('Z','+00:00'))
            if value.tzinfo:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            record['timestamp_utc'] = value
        if isinstance(record.get('calendar_date'), str):
            record['calendar_date'] = date.fromisoformat(record['calendar_date'])
        if any(value is None for value in record.values()):
            raise ValueError('Parquet records must not contain missing required values')
        result.append(record)
    return pa.Table.from_pylist(result, schema=schema).to_pylist()


def parquet_bytes(rows, schema):
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), sink,
                   compression='snappy', coerce_timestamps='us', version='2.6')
    return sink.getvalue().to_pybytes()


def upsert(s3, bucket, key, rows, schema, primary_key):
    incoming = normalize(rows, schema)
    if len({r[primary_key] for r in incoming}) != len(incoming):
        raise ValueError('Duplicate keys in incoming Parquet batch')
    for attempt in range(5):
        listing = s3.list_objects_v2(Bucket=bucket, Prefix=key, MaxKeys=1)
        existing, etag = [], None
        if any(o['Key'] == key for o in listing.get('Contents', [])):
            response = s3.get_object(Bucket=bucket, Key=key)
            etag = response['ETag']
            with response['Body'] as stream:
                existing = pq.read_table(pa.BufferReader(stream.read())).to_pylist()
        merged = {r[primary_key]: r for r in existing}
        merged.update({r[primary_key]: r for r in incoming})
        output = [merged[k] for k in sorted(merged)]
        # ETag preconditions prevent concurrent runs from silently losing each other's rows.
        condition = {'IfMatch':etag} if etag else {'IfNoneMatch':'*'}
        try:
            s3.put_object(Bucket=bucket, Key=key, Body=parquet_bytes(output, schema),
                          ContentType='application/vnd.apache.parquet', ServerSideEncryption='AES256', **condition)
            return {'key':key, 'rows':len(output)}
        except ClientError as exc:
            # S3 conditional-write errors have no dedicated modeled boto3 exception.
            if exc.response['Error']['Code'] not in ('PreconditionFailed','ConditionalRequestConflict','412','409') or attempt == 4:
                raise
    raise RuntimeError('Parquet write conflict')


def publish(s3, bucket, demand, weather, joined):
    results = []
    for table, rows in [('hourly_demand',demand), ('hourly_weather',weather), ('hourly_demand_weather',joined)]:
        groups = defaultdict(list)
        for row in rows:
            groups[row['timestamp_utc'][:7]].append(row)
        for month, batch in sorted(groups.items()):
            key = f'curated/parquet/{table}/region=DUK/year={month[:4]}/month={month[5:]}/part-00000.parquet'
            results.append(upsert(s3,bucket,key,batch,SCHEMAS[table],'timestamp_utc'))
    days = sorted({r['timestamp_utc'][:10] for r in demand + weather})
    calendar = []
    for value in days:
        day = date.fromisoformat(value)
        calendar.append(dict(calendar_date=day,day_of_week=day.isoweekday(),is_weekend=day.weekday()>=5,
                             month_number=day.month,year_number=day.year))
    if calendar:
        results.append(upsert(s3,bucket,'curated/parquet/dim_calendar/part-00000.parquet',calendar,
                              SCHEMAS['dim_calendar'],'calendar_date'))
    region = [dict(region='DUK',region_name='Duke Energy Carolinas',local_timezone='America/New_York',
                   weather_latitude=35.2271,weather_longitude=-80.8431)]
    results.append(upsert(s3,bucket,'curated/parquet/dim_region/part-00000.parquet',region,SCHEMAS['dim_region'],'region'))
    return results
