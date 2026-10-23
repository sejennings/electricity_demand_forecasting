import csv
import hashlib
import io
import unittest
from scripts.export_dashboard import build_run, export, write_snapshot


class DashboardTests(unittest.TestCase):
    def test_aws_refresh_requires_same_origin_and_is_rate_limited(self):
        import threading
        from functools import partial
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        from unittest.mock import patch
        from scripts.serve_dashboard import DashboardHandler, DashboardServer, ROOT
        class QuietHandler(DashboardHandler):
            def log_message(self, *args):
                pass
        with DashboardServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT))) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            url=f'http://127.0.0.1:{server.server_port}'
            try:
                with patch('scripts.serve_dashboard.refresh_snapshot') as refresh:
                    request=Request(url+'/api/refresh',data=b'',headers={'Origin':'https://unrelated.example','X-GridCast-Refresh':'1'})
                    with self.assertRaises(HTTPError) as error: urlopen(request,timeout=5)
                    self.assertEqual(error.exception.code,403)
                    refresh.assert_not_called()
                    request=Request(url+'/api/refresh',data=b'',headers={'Origin':url,'X-GridCast-Refresh':'1'})
                    with urlopen(request,timeout=5) as response:self.assertEqual(response.status,200)
                    refresh.assert_called_once()
                    with self.assertRaises(HTTPError) as error:urlopen(request,timeout=5)
                    self.assertEqual(error.exception.code,429)
                    refresh.assert_called_once()
            finally:
                server.shutdown()
                thread.join(timeout=5)

    def test_local_server_exposes_only_known_assets(self):
        import tempfile
        import threading
        from functools import partial
        from http.server import ThreadingHTTPServer
        from pathlib import Path
        from urllib.error import HTTPError
        from urllib.request import urlopen
        from scripts.serve_dashboard import DashboardHandler
        class QuietHandler(DashboardHandler):
            def log_message(self, *args):
                pass
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'index.html').write_text('dashboard')
            (root/'private.tmp').write_text('not a dashboard asset')
            with ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=folder)) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True)
                thread.start()
                try:
                    url=f'http://127.0.0.1:{server.server_port}'
                    with urlopen(url+'/?demo=1',timeout=5) as response:
                        self.assertEqual(response.read(),b'dashboard')
                        self.assertEqual(response.headers['Cache-Control'],'no-store')
                    for path in ['/private.tmp','/../AGENTS.md']:
                        with self.assertRaises(HTTPError) as error:
                            urlopen(url+path,timeout=5)
                        self.assertEqual(error.exception.code,404)
                finally:
                    server.shutdown()
                    thread.join(timeout=5)

    def test_invalid_scores_and_empty_forecasts_are_rejected(self):
        manifest=self.fixture()
        base=dict(forecast_sha256=manifest['forecast_sha256'],issue_time_utc=manifest['issue_time_utc'])
        for rows in [
            [dict(timestamp_utc='2026-10-21T01:00:00Z',actual_mw=float('nan'))],
            [dict(timestamp_utc='2026-10-22T01:00:00Z',actual_mw=80)],
            [dict(timestamp_utc='2026-10-21T01:00:00Z',actual_mw=80)]*2,
        ]:
            with self.assertRaises(ValueError): build_run(manifest,dict(base,rows=rows))
        with self.assertRaisesRegex(ValueError,'before its hour ended'):
            build_run(manifest,dict(base,rows=[dict(timestamp_utc='2026-10-21T01:00:00Z',actual_mw=80)],
                                    scored_at_utc='2026-10-21T01:30:00Z'))
        manifest['forecast_csv']='timestamp_utc,horizon_hours,forecast_mw\n'
        manifest['forecast_sha256']=hashlib.sha256(manifest['forecast_csv'].encode()).hexdigest()
        with self.assertRaisesRegex(ValueError,'Empty forecast'): build_run(manifest)

    def test_failed_snapshot_write_preserves_last_good_data(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'snapshot.json'
            path.write_text('last good snapshot')
            with self.assertRaises(ValueError): write_snapshot(path,{'bad':float('nan')})
            self.assertEqual(path.read_text(),'last good snapshot')
            self.assertEqual(list(Path(folder).glob('*.tmp')),[])
            write_snapshot(path,{'runs':[]})
            self.assertIn('runs',path.read_text())

    def test_manifest_allowance_fails_before_downloads(self):
        from unittest.mock import Mock
        session=Mock();s3=session.client.return_value
        s3.get_paginator.return_value.paginate.return_value=[{'Contents':[
            {'Key':'forecasts/runs/a/manifest.json'}, {'Key':'forecasts/runs/b/manifest.json'}]}]
        with self.assertRaisesRegex(ValueError,'Manifest allowance'):
            export(session,limit=1,max_manifests=1)
        s3.get_object.assert_not_called()

    def fixture(self):
        rows=[dict(timestamp_utc=f'2026-10-21T{h:02}:00:00Z',horizon_hours=h,forecast_mw=100)
              for h in [1,2]]
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
        raw=stream.getvalue()
        return dict(forecast_id='issue',forecast_csv=raw,forecast_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                    issue_time_utc='2026-10-21T00:30:00Z',forecast_origin_utc=rows[0]['timestamp_utc'],model_sha256='model')

    def test_missing_actuals_stay_pending_and_do_not_dilute_error(self):
        manifest=self.fixture()
        pending=build_run(manifest)
        self.assertEqual(pending['status'],'pending')
        self.assertIsNone(pending['metrics']['wape_percent'])
        score=dict(forecast_sha256=manifest['forecast_sha256'],issue_time_utc=manifest['issue_time_utc'],
                   rows=[dict(timestamp_utc='2026-10-21T01:00:00Z',actual_mw=80)])
        partial=build_run(manifest,score)
        self.assertEqual(partial['status'],'partial')
        self.assertEqual(partial['metrics']['wape_percent'],25)
        self.assertIsNone(partial['rows'][1]['actual_mw'])

    def test_rejects_tampered_forecast_and_mismatched_score(self):
        manifest=self.fixture()
        with self.assertRaisesRegex(ValueError,'does not belong'):
            build_run(manifest,dict(forecast_sha256='another issue',issue_time_utc=manifest['issue_time_utc']))
        manifest['forecast_csv']+='tampered'
        with self.assertRaisesRegex(ValueError,'integrity'):
            build_run(manifest)
