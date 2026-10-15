import unittest
from datetime import timedelta
from gridcast.baselines import HOUR, evaluate, instant, metrics, predict


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.start = instant('2025-01-01T00:00:00Z')
        self.data = {self.start + h * HOUR: float(h + 100) for h in range(24 * 12)}
        self.issue = self.start + timedelta(days=8)

    def test_predictions_cannot_see_future(self):
        expected = predict(self.data, self.issue)
        changed = {t: v if t < self.issue else 999999 for t, v in self.data.items()}
        self.assertEqual(expected, predict(changed, self.issue))
        daily = [r['forecast_mw'] for r in expected if r['model'] == 'daily_naive']
        self.assertEqual(daily[0], self.data[self.issue - 24 * HOUR])
        self.assertEqual(daily[-1], self.data[self.issue - HOUR])

    def test_delay_applies_to_every_horizon(self):
        cutoff = self.issue - 6 * HOUR
        expected = predict(self.data, self.issue, 6)
        changed = {t: v if t < cutoff else 999999 for t, v in self.data.items()}
        self.assertEqual(expected, predict(changed, self.issue, 6))

    def test_shared_daily_coverage(self):
        del self.data[self.issue + HOUR]
        rows, report = evaluate(self.data, self.issue, self.issue + timedelta(days=2))
        self.assertEqual(report['evaluated_days'], 1)
        self.assertEqual(report['skipped_incomplete_days'], 2)
        self.assertEqual(len(rows), 96)

    def test_known_metrics(self):
        result = metrics([{'actual_mw': 10, 'forecast_mw': 12}, {'actual_mw': 20, 'forecast_mw': 18}])
        self.assertEqual(result['mae_mw'], 2)
        self.assertEqual(result['rmse_mw'], 2)
        self.assertAlmostEqual(result['wape_percent'], 100 * 4 / 30)
        self.assertIsNone(metrics([{'actual_mw': 0, 'forecast_mw': 1}])['wape_percent'])

    def test_utc_required(self):
        with self.assertRaises(ValueError):
            instant('2025-01-01T00:00:00')
