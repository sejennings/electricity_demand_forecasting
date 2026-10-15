import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from gridcast.ingestion import cached_request, demand_rows, month_windows, quality, timestamp


class ImportTests(unittest.TestCase):
    def test_leap_month(self):
        self.assertEqual(len(list(month_windows(date(2024, 2, 28), date(2024, 3, 1)))), 2)

    def test_quality_and_utc(self):
        self.assertEqual(timestamp('2025-01-01T01:00+01:00'), '2025-01-01T00:00:00Z')
        row = {'timestamp_utc': timestamp('2025-01-01T00'), 'demand_mw': None}
        self.assertEqual(quality([row], date(2025, 1, 1), date(2025, 1, 1), ['demand_mw'])['missing_hours'], 23)
        with self.assertRaises(ValueError):
            quality([row, row], date(2025, 1, 1), date(2025, 1, 1), [])

    def test_cache_hides_key(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'raw.json'
            with patch('gridcast.ingestion.request_json', return_value={'request': {'api_key': 'secret'}, 'response': {}}) as fetch:
                cached_request(path, 'url', {})
                cached_request(path, 'url', {})
                self.assertEqual(fetch.call_count, 1)
                self.assertNotIn('secret', path.read_text())

    def test_pagination(self):
        def page(hour):
            return {'response': {'total': '2', 'data': [{'period': f'2025-01-01T{hour:02}', 'respondent': 'DUK', 'type': 'D', 'value': '1234.5', 'value-units': 'megawatthours'}]}}
        with patch('gridcast.ingestion.cached_request', side_effect=[page(0), page(1)]) as fetch:
            rows = demand_rows(date(2025, 1, 1), date(2025, 1, 1), 'DUK', Path('data'), 'key')
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['demand_mw'], 1234.5)
            self.assertEqual(fetch.call_args_list[1].args[2]['offset'], 1)
