import unittest
from datetime import timedelta
from gridcast.baselines import HOUR, instant
from gridcast.research import features


class ResearchTests(unittest.TestCase):
    def test_features_ignore_unavailable_demand(self):
        issue = instant('2025-01-20T00:00:00Z')
        data = {issue - h * HOUR: float(h) for h in range(-24, 600)}
        cutoff = issue - 24 * HOUR
        changed = {t: v if t < cutoff else 999999 for t, v in data.items()}
        for h in range(24):
            self.assertEqual(features(data, issue, issue+h*HOUR), features(changed, issue, issue+h*HOUR))

    def test_missing_history_is_not_filled(self):
        issue = instant('2025-01-20T00:00:00Z')
        self.assertIsNone(features({}, issue, issue))
