import json
import unittest
from unittest.mock import patch
from gridcast.publish_dashboard import handler, public_snapshot


class PublicDashboardTests(unittest.TestCase):
    def test_public_build_omits_local_snapshot_and_refresh_endpoint(self):
        import tempfile
        from pathlib import Path
        from scripts.build_public_dashboard import build
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            build(output)
            self.assertEqual({p.name for p in output.iterdir()},
                             {'index.html', 'app.js', 'style.css', 'demo.json'})
            html = (output / 'index.html').read_text(encoding='utf-8')
            self.assertIn('data-snapshot-url="https://', html)
            self.assertIn('id="sync" hidden', html)

    def snapshot(self):
        from pathlib import Path
        return json.loads(Path('dashboard/demo.json').read_text())

    def test_public_summary_drops_internal_fields(self):
        snapshot = self.snapshot()
        snapshot['credential'] = 'private'
        snapshot['runs'][0]['image_uri'] = 'private-ecr-uri'
        snapshot['runs'][0]['rows'][0]['internal'] = 'private'
        snapshot['pipelines'][0]['executions'][0]['name'] = 'private-execution'
        public = public_snapshot(snapshot)
        encoded = json.dumps(public)
        self.assertNotIn('private', encoded)
        self.assertTrue(public['public'])
        self.assertEqual(public['runs'][0]['rows'][0]['forecast_mw'],
                         snapshot['runs'][0]['rows'][0]['forecast_mw'])

    @patch('gridcast.publish_dashboard.boto3.Session')
    @patch('gridcast.publish_dashboard.export')
    def test_export_failure_preserves_published_data(self, export, session):
        export.side_effect = ValueError('Invalid forecast')
        with self.assertRaises(ValueError):
            handler({}, None)
        session.return_value.client.assert_not_called()

    @patch.dict('os.environ', {'PUBLIC_BUCKET': 'public-summary'})
    @patch('gridcast.publish_dashboard.boto3.Session')
    @patch('gridcast.publish_dashboard.export')
    def test_publisher_writes_only_summary_object(self, export, session):
        export.return_value = self.snapshot()
        handler({}, None)
        call = session.return_value.client.return_value.put_object.call_args.kwargs
        self.assertEqual((call['Bucket'], call['Key']), ('public-summary', 'snapshot.json'))
        self.assertEqual(call['CacheControl'], 'public,max-age=300')
        self.assertNotIn('image_uri', json.loads(call['Body'])['runs'][0])

    @patch('gridcast.publish_dashboard.boto3.Session')
    @patch('gridcast.publish_dashboard.export', return_value={
        'generated_at_utc': '2026-10-25T14:15:00Z', 'runs': [], 'pipelines': []})
    def test_empty_archive_preserves_published_data(self, export, session):
        with self.assertRaises(ValueError):
            handler({}, None)
        session.return_value.client.assert_not_called()
