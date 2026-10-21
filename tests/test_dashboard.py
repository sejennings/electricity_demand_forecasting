import csv
import hashlib
import io
import unittest
from scripts.export_dashboard import build_run


class DashboardTests(unittest.TestCase):
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
