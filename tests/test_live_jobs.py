import csv
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from gridcast.baselines import HOUR,instant
from gridcast.ingestion import timestamp,write_csv,write_json
from gridcast.jobs import forecast
from gridcast.live import recent_demand


class Predictor:
    def predict(self,X):
        return np.array(X)[:,5]


class LiveTests(unittest.TestCase):
    def test_export_fallback_keeps_observed_values_and_applies_latest_revision(self):
        latest={'period':'2025-01-02T11','respondent':'DUK','type':'D','value':'110','value-units':'megawatthours'}
        exported=[dict(timestamp_utc='2025-01-02T10:00:00Z',region='DUK',demand_mw=100),
                  dict(timestamp_utc='2025-01-02T11:00:00Z',region='DUK',demand_mw=105)]
        with patch('gridcast.live.cached_request',side_effect=[RuntimeError('API timeout'),{'response':{'data':[latest]}}]), \
             patch('gridcast.eia_export.download'),patch('gridcast.eia_export.read_rows',return_value=exported):
            rows,report=recent_demand('not-a-real-key',Path('unused'),datetime(2025,1,2,12,34,tzinfo=timezone.utc))
        self.assertEqual([r['demand_mw'] for r in rows],[100,110])
        self.assertEqual(report['retrieval_source'],'eia-published-hourly-export-plus-latest-api')
    def test_demand_request_stops_before_current_hour(self):
        record={'period':'2025-01-02T11','respondent':'DUK','type':'D','value':'100','value-units':'megawatthours'}
        with patch('gridcast.live.cached_request',return_value={'response':{'total':'1','data':[record]}}) as request:
            rows,report=recent_demand('not-a-real-key',Path('unused'),datetime(2025,1,2,12,34,tzinfo=timezone.utc))
        self.assertEqual(request.call_args.args[2]['sort[0][direction]'],'desc')
        self.assertEqual(request.call_args.args[2]['length'],1000)
        self.assertEqual(report['request_end_utc'],'2025-01-02T11:00:00Z')
        self.assertEqual(report['latest_observation_utc'],'2025-01-02T11:00:00Z')

    def fixture(self,root):
        issued=datetime(2025,2,1,12,30,tzinfo=timezone.utc)
        origin=issued.replace(minute=0)+HOUR
        demand=[dict(timestamp_utc=timestamp(instant('2025-01-01T00:00:00Z')+h*HOUR),region='DUK',demand_mw=100+h) for h in range(31*24)]
        weather=[dict(timestamp_utc=timestamp(origin+h*HOUR),available_at_utc='2025-02-01T12:00:00Z',temperature_2m=10) for h in range(24)]
        write_csv(root/'demand.csv',demand);write_csv(root/'weather.csv',weather)
        manifest=dict(snapshot_id='test',completed_at_utc='2025-02-01T12:00:00Z',demand_file='demand.csv',weather_file='weather.csv')
        write_json(root/'manifest.json',manifest)
        write_json(root/'latest.json',{'snapshot_manifest':'manifest.json'})
        artifact=dict(model=Predictor(),availability_delay_hours=24,region='DUK',training_cutoff_exclusive='2025-01-01T00:00:00Z')
        (root/'model').write_bytes(b'trusted-test-placeholder')
        return issued,artifact,demand

    def test_portable_snapshot_and_no_demand_leakage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);issued,artifact,demand=self.fixture(root)
            with patch('gridcast.jobs.load',return_value=artifact):
                first=forecast(root/'model',root/'latest.json',root/'out',issued)
                with first.open() as stream:
                    original=list(csv.DictReader(stream))
                cutoff=issued.replace(minute=0)+HOUR-timedelta(hours=24)
                for row in demand:
                    if instant(row['timestamp_utc'])>=cutoff: row['demand_mw']=999999
                write_csv(root/'demand.csv',demand)
                second=forecast(root/'model',root/'latest.json',root/'out',issued)
                with second.open() as stream:
                    changed=list(csv.DictReader(stream))
            self.assertEqual([r['forecast_mw'] for r in original],[r['forecast_mw'] for r in changed])
            self.assertEqual(len(original),24)
            self.assertNotEqual(first,second)

    def test_forecast_rejects_unavailable_inputs_and_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);issued,artifact,_=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'Snapshot'):
                forecast(root/'model',root/'manifest.json',root/'out',issued-timedelta(hours=1))
            artifact['training_cutoff_exclusive']='2025-02-01T00:00:00Z'
            with patch('gridcast.jobs.load',return_value=artifact),self.assertRaisesRegex(ValueError,'training'):
                forecast(root/'model',root/'manifest.json',root/'out',issued)

    def test_missing_demand_history_is_not_filled(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);issued,artifact,demand=self.fixture(root)
            write_csv(root/'demand.csv',demand[:24])
            with patch('gridcast.jobs.load',return_value=artifact),self.assertRaisesRegex(ValueError,'Missing required demand'):
                forecast(root/'model',root/'manifest.json',root/'out',issued)

    def test_future_weather_vintage_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);issued,artifact,_=self.fixture(root)
            with (root/'weather.csv').open() as stream:
                rows=list(csv.DictReader(stream))
            rows[0]['available_at_utc']='2025-02-01T13:00:00Z'
            write_csv(root/'weather.csv',rows)
            with patch('gridcast.jobs.load',return_value=artifact),self.assertRaisesRegex(ValueError,'weather'):
                forecast(root/'model',root/'manifest.json',root/'out',issued)
