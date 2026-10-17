import json
import os
import unittest
from datetime import date
from unittest.mock import patch
from gridcast.cloud import curate, ingest, partition, validate, window


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.etags = {}

    def put_object(self, **kwargs):
        self.objects[kwargs['Key']] = kwargs['Body']
        self.etags[kwargs['Key']] = str(len(self.etags) + 1)

    def get_object(self, **kwargs):
        import io
        return {'Body': io.BytesIO(self.objects[kwargs['Key']]), 'ETag': self.etags.get(kwargs['Key'], 'initial')}

    def list_objects_v2(self, **kwargs):
        keys = sorted(k for k in self.objects if k.startswith(kwargs['Prefix']))[:kwargs.get('MaxKeys',1000)]
        return {'Contents':[{'Key':k} for k in keys]}

    def upload_file(self, *args, **kwargs):
        pass


class CloudTests(unittest.TestCase):
    def test_bounded_windows(self):
        self.assertEqual(window({'end_date': '2025-01-07', 'days': 7}), (date(2025,1,1), date(2025,1,7)))
        with self.assertRaises(ValueError):
            window({'end_date': '2025-01-07', 'days': 100})

    def test_incomplete_data_never_published(self):
        s3 = FakeS3()
        with patch.dict(os.environ, {'LAKE_BUCKET':'test'}), patch('gridcast.cloud.weather_rows', return_value=[]):
            with self.assertRaises(ValueError):
                ingest({'source':'weather', 'run_id':'test', 'end_date':'2025-01-01', 'days':1}, s3, None)
        self.assertFalse(any(k.startswith('processed/') for k in s3.objects))
        self.assertTrue(any(k.startswith('reports/') for k in s3.objects))

    def test_complete_join(self):
        s3 = FakeS3()
        demand, weather = [], []
        for hour in range(24):
            ts = f'2025-01-01T{hour:02}:00:00Z'
            demand.append(dict(timestamp_utc=ts, region='DUK', demand_mw=100))
            weather.append(dict(timestamp_utc=ts, temperature_2m=10, relative_humidity_2m=50, precipitation=0,
                                wind_speed_10m=1, latitude=35.2271, longitude=-80.8431, weather_source='open-meteo-era5'))
        prefix = partition(date(2025,1,1))
        for source, rows in [('demand',demand),('weather',weather)]:
            s3.objects[f'processed/{source}/{prefix}/data.json'] = json.dumps(rows).encode()
        with patch.dict(os.environ, {'LAKE_BUCKET':'test'}):
            result = curate({'end_date':'2025-01-01','days':1,'run_id':'test'}, s3)
        self.assertEqual(result['rows'], 24)
        self.assertIn(f'curated/hourly/{prefix}/data.csv', s3.objects)

    def test_nonpositive_demand_rejected(self):
        with self.assertRaises(ValueError):
            validate([dict(timestamp_utc=f'2025-01-01T{h:02}:00:00Z', demand_mw=0) for h in range(24)],
                     date(2025,1,1), date(2025,1,1), ['demand_mw'])
