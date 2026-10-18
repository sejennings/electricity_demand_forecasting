"""Vintage selection and forecast feature contract regression tests."""
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from gridcast.baselines import HOUR, instant
from gridcast.ingestion import timestamp, write_csv, write_json
from gridcast.jobs import forecast, train
from gridcast.vintages import Archive, SCHEMA, MODEL, weather_features
import test_live_jobs


def row(run, target, value=10):
    return dict(run_utc=timestamp(run),timestamp_utc=timestamp(target),
        available_at_utc=timestamp(run+12*HOUR),model=MODEL,
        availability_basis='assumed_initialization_plus_12h',temperature_2m=value,
        relative_humidity_2m=50,precipitation=0,wind_speed_10m=2)


class WeatherPredictor:
    def predict(self,X):
        assert np.array(X).shape[1]==19
        return np.array(X)[:,13]+100


class VintageTests(unittest.TestCase):
    def test_latest_available_run_and_future_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'weather.csv'
            issue=instant('2026-06-01T00:00:00Z'); target=issue+HOUR
            rows=[row(issue-24*HOUR,target,1),row(issue-12*HOUR,target,2),row(issue-6*HOUR,target,999)]
            write_csv(p,rows)
            self.assertEqual(Archive([p]).select(issue,target)['temperature_2m'],'2')
            rows[-1]['temperature_2m']=-999
            write_csv(p,rows)
            self.assertEqual(Archive([p]).select(issue,target)['temperature_2m'],'2')
            self.assertIsNone(Archive([p]).select(issue-48*HOUR,target))

    def test_rejects_invalid_timing_nonfinite_and_conflicts(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'weather.csv'
            run=instant('2026-06-01T00:00:00Z'); r=row(run,run+24*HOUR)
            r['available_at_utc']=timestamp(run)
            write_csv(p,[r])
            with self.assertRaisesRegex(ValueError,'timing'): Archive([p])
            with self.assertRaises(ValueError): weather_features({**r,'temperature_2m':'nan'})
            a=row(run,run+24*HOUR); b={**a,'temperature_2m':20}
            write_csv(p,[a,b])
            with self.assertRaisesRegex(ValueError,'Conflicting'): Archive([p])

    def test_weather_model_inference_and_source_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            issued,artifact,_=test_live_jobs.LiveTests().fixture(root)
            artifact.update(model=WeatherPredictor(),uses_weather=True,weather_schema=SCHEMA,weather_model=MODEL)
            manifest=__import__('json').loads((root/'manifest.json').read_text())
            manifest['weather']={'model_requested':MODEL}
            write_json(root/'manifest.json',manifest)
            with (root/'weather.csv').open() as stream: weather=list(csv.DictReader(stream))
            for w in weather: w.update(relative_humidity_2m=50,precipitation=0,wind_speed_10m=2)
            write_csv(root/'weather.csv',weather)
            with patch('gridcast.jobs.load',return_value=artifact):
                out=forecast(root/'model',root/'manifest.json',root/'out',issued)
                with out.open() as stream: result=list(csv.DictReader(stream))
                self.assertTrue(all(r['forecast_mw']=='110.0' and r['weather_used_by_model']=='True' for r in result))
                manifest['weather']['model_requested']='different-model'
                write_json(root/'manifest.json',manifest)
                with self.assertRaisesRegex(ValueError,'differs'): forecast(root/'model',root/'manifest.json',root/'out',issued)

    def test_training_does_not_substitute_missing_weather(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);test_live_jobs.LiveTests().fixture(root)
            run=instant('2025-01-15T12:00:00Z')
            write_csv(root/'vintages.csv',[row(run,run+12*HOUR)])
            with self.assertRaisesRegex(ValueError,'30 days'):
                train([root/'demand.csv'],instant('2025-02-01T00:00:00Z'),root/'artifact',[root/'vintages.csv'])
