"""Unit tests for sdn/playout_model.py (no network needed)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from playout_model import simulate  # noqa: E402

R = 4e6  # video bitrate, bit/s


class PlayoutModelTest(unittest.TestCase):
    def test_full_rate_never_stalls(self):
        r = simulate([R] * 30, 1.0, R)
        self.assertEqual(r['startup_delay_s'], 2.0)
        self.assertEqual(r['stall_count'], 0)
        self.assertEqual(r['stall_time_s'], 0.0)

    def test_half_rate_stalls(self):
        # 10 s at full rate, then half rate: the buffer drains and stalls.
        r = simulate([R] * 10 + [R / 2] * 20, 1.0, R)
        self.assertGreaterEqual(r['stall_count'], 1)
        self.assertGreater(r['stall_time_s'], 0)

    def test_short_dip_absorbed_by_buffer(self):
        # Buffer stays at the 2 s it collected before starting; a 1 s dip
        # to zero uses part of it but does not stall.
        r = simulate([R] * 10 + [0] + [R] * 10, 1.0, R)
        self.assertEqual(r['stall_count'], 0)

    def test_outage_counts_one_stall(self):
        r = simulate([R] * 5 + [0] * 5 + [R] * 10, 1.0, R)
        self.assertEqual(r['stall_count'], 1)

    def test_no_data_never_starts(self):
        r = simulate([0] * 10, 1.0, R)
        self.assertIsNone(r['startup_delay_s'])
        self.assertEqual(r['stall_count'], 0)


if __name__ == '__main__':
    unittest.main()
