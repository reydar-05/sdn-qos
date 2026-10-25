"""Unit tests for sdn/monitor.py. No network or sudo needed:
    .venv/bin/python -m unittest discover -s sdn/tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from monitor import CongestionDetector, RateTracker  # noqa: E402


class RateTrackerTest(unittest.TestCase):
    def test_first_sample_has_no_rate(self):
        r = RateTracker()
        self.assertEqual(r.update('p', 0.0, {'tx': 0}), (None, 'first sample'))

    def test_rate_from_delta(self):
        r = RateTracker()
        r.update('p', 10.0, {'tx': 1000})
        rates, dt = r.update('p', 12.0, {'tx': 3500})
        self.assertEqual(dt, 2.0)
        self.assertEqual(rates['tx'], 1250.0)

    def test_late_reply_uses_counter_time(self):
        # The reply arrived late, but the switch timestamps are 4 s apart,
        # so the rate is still correct.
        r = RateTracker()
        r.update('p', 0.0, {'tx': 0})
        rates, dt = r.update('p', 4.0, {'tx': 4000})
        self.assertEqual(rates['tx'], 1000.0)

    def test_counter_reset_is_skipped_and_rebased(self):
        r = RateTracker()
        r.update('p', 0.0, {'tx': 5000})
        self.assertEqual(r.update('p', 2.0, {'tx': 100}), (None, 'counter reset'))
        rates, _ = r.update('p', 4.0, {'tx': 300})
        self.assertEqual(rates['tx'], 100.0)

    def test_no_time_passed(self):
        r = RateTracker()
        r.update('p', 1.0, {'tx': 0})
        self.assertEqual(r.update('p', 1.0, {'tx': 10}), (None, 'no time passed'))


class CongestionDetectorTest(unittest.TestCase):
    def test_needs_n_consecutive_polls(self):
        d = CongestionDetector(0.8, 3)
        self.assertIsNone(d.update('l', 0.9))
        self.assertIsNone(d.update('l', 0.9))
        self.assertEqual(d.update('l', 0.9), 'detected')
        self.assertTrue(d.is_congested('l'))
        self.assertIsNone(d.update('l', 0.95))  # reported once, not every poll

    def test_one_dip_resets_the_count(self):
        d = CongestionDetector(0.8, 3)
        d.update('l', 0.9)
        d.update('l', 0.9)
        d.update('l', 0.5)  # spike was not sustained
        self.assertIsNone(d.update('l', 0.9))
        self.assertIsNone(d.update('l', 0.9))
        self.assertEqual(d.update('l', 0.9), 'detected')

    def test_threshold_itself_is_not_over(self):
        d = CongestionDetector(0.8, 1)
        self.assertIsNone(d.update('l', 0.8))

    def test_clear_needs_n_polls_under(self):
        d = CongestionDetector(0.8, 2)
        d.update('l', 0.9)
        d.update('l', 0.9)
        self.assertIsNone(d.update('l', 0.5))
        self.assertIsNone(d.update('l', 0.9))  # back over: clearing restarts
        self.assertIsNone(d.update('l', 0.5))
        self.assertEqual(d.update('l', 0.5), 'cleared')
        self.assertFalse(d.is_congested('l'))

    def test_links_are_independent(self):
        d = CongestionDetector(0.8, 2)
        d.update('a', 0.9)
        d.update('b', 0.9)
        self.assertEqual(d.update('a', 0.9), 'detected')
        self.assertFalse(d.is_congested('b'))


if __name__ == '__main__':
    unittest.main()
