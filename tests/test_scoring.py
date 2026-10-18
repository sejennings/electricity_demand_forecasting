import csv
from datetime import timedelta
import hashlib
import io
import json
import unittest
from gridcast.baselines import instant
from gridcast.scoring import score_rows, score_archive


class Missing(Exception): pass


class Store:
    class exceptions:
        NoSuchKey=Missing
    def __init__(self): self.objects={}; self.writes=[]
    def get_object(self, Bucket, Key):
        if Key not in self.objects: raise Missing(Key)
        return {'Body':io.BytesIO(self.objects[Key]),'ETag':hashlib.sha256(self.objects[Key]).hexdigest()}
    def put_object(self, Bucket, Key, Body, **kwargs):
        if kwargs.get('IfNoneMatch')=='*' and Key in self.objects: raise AssertionError('Immutable write repeated')
        self.objects[Key]=Body; self.writes.append(Key)
    def get_paginator(self, name): return self
    def list_objects_v2(self,Bucket,Prefix,MaxKeys):
        return {'Contents':[{'Key':k} for k in sorted(self.objects) if k.startswith(Prefix)][:MaxKeys]}
    def paginate(self, Bucket, Prefix):
        yield {'Contents':[{'Key':k} for k in self.objects if k.startswith(Prefix)]}


class ScoringTests(unittest.TestCase):
    def rows(self, issue='2026-10-17T12:30:00Z', value=110):
        return [dict(issue_time_utc=issue,timestamp_utc='2026-10-17T13:00:00Z',
            horizon_hours=1,forecast_mw=value),dict(issue_time_utc=issue,
            timestamp_utc='2026-10-17T14:00:00Z',horizon_hours=2,forecast_mw=value)]

    def test_pending_partial_complete_and_future_actuals(self):
        rows=self.rows(); actuals={r['timestamp_utc']:100 for r in rows}
        pending=score_rows(rows,actuals,instant('2026-10-17T13:00:00Z'))
        self.assertEqual(pending['status'],'pending'); self.assertIsNone(pending['metrics']['mae_mw'])
        partial=score_rows(rows,actuals,instant('2026-10-17T14:00:00Z'))
        self.assertEqual(partial['status'],'partial'); self.assertEqual(partial['scored_hours'],1)
        complete=score_rows(rows,actuals,instant('2026-10-17T15:00:00Z'))
        self.assertEqual(complete['status'],'complete'); self.assertEqual(complete['metrics']['wape_percent'],10)
        self.assertEqual(complete['issue_time_utc'],rows[0]['issue_time_utc'])
        self.assertEqual(complete['rows'][0]['error_mw'],10)

    def test_invalid_records_rejected(self):
        rows=self.rows()
        with self.assertRaisesRegex(ValueError,'duplicate'): score_rows(rows+rows,{},instant('2026-10-18T00:00:00Z'))
        rows[0]['issue_time_utc']='2026-10-17T11:30:00Z'
        with self.assertRaisesRegex(ValueError,'Mixed'): score_rows(rows,{},instant('2026-10-18T00:00:00Z'))
        with self.assertRaisesRegex(ValueError,'actual'): score_rows(self.rows(),{self.rows()[0]['timestamp_utc']:float('nan')},instant('2026-10-18T00:00:00Z'))

    def manifest(self,store,name,rows):
        stream=io.StringIO(newline=''); writer=csv.DictWriter(stream,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        raw=stream.getvalue()
        m=dict(forecast_id=name,forecast_csv=raw,forecast_sha256=hashlib.sha256(raw.encode()).hexdigest(),model_sha256='test-model')
        store.objects[f'forecasts/runs/{name}/manifest.json']=json.dumps(m).encode()

    def test_revisions_replay_and_overlapping_issues_are_separate(self):
        store=Store(); self.manifest(store,'first',self.rows()); self.manifest(store,'second',self.rows('2026-10-17T12:00:00Z',120))
        now=instant('2026-10-18T00:00:00Z')
        actuals={r['timestamp_utc']:100 for r in self.rows()}
        first=score_archive(store,'test',now,actuals,'snapshot-a')
        self.assertEqual(len(first),2)
        revisions=[k for k in store.objects if '/revisions/' in k]; self.assertEqual(len(revisions),2)
        score_archive(store,'test',now+timedelta(hours=1),actuals,'snapshot-b')
        self.assertEqual(len([k for k in store.objects if '/revisions/' in k]),2)
        actuals[self.rows()[0]['timestamp_utc']]=105
        score_archive(store,'test',now+timedelta(hours=2),actuals,'snapshot-c')
        self.assertEqual(len([k for k in store.objects if '/revisions/' in k]),4)
        self.assertTrue(all(k in store.objects for k in revisions))
        original=json.loads(store.objects[revisions[0]])
        self.assertEqual(original['actual_snapshot_id'],'snapshot-a')
        pointers={k:v for k,v in store.objects.items() if k.endswith('/latest.json')}
        score_archive(store,'test',now,{},'older-concurrent-run')
        self.assertEqual({k:v for k,v in store.objects.items() if k.endswith('/latest.json')},pointers)

    def test_forecast_tampering_rejected(self):
        store=Store(); self.manifest(store,'first',self.rows())
        key='forecasts/runs/first/manifest.json'; value=json.loads(store.objects[key]); value['forecast_csv']+='changed'
        store.objects[key]=json.dumps(value).encode()
        with self.assertRaisesRegex(ValueError,'hash mismatch'): score_archive(store,'test',instant('2026-10-18T00:00:00Z'))
