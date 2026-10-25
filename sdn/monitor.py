"""
Monitoring logic, kept free of Ryu so it can be unit-tested without a
network (see sdn/tests/test_monitor.py).

RateTracker        turns cumulative counters (bytes so far) into rates.
CongestionDetector decides when a link is congested, with N-poll
                   confirmation in both directions.
"""


class RateTracker:
    """Rates from cumulative counters.

    Switches report totals ("this port has sent 123456 bytes since it
    came up"). The rate is the change between two samples divided by the
    time between them. The time comes from the switch's own counter clock
    when available, so a reply that arrives late still gives a correct
    rate.
    """

    def __init__(self):
        self.last = {}

    def update(self, key, t, counters):
        """Return ({name: per-second rate}, dt) or (None, reason)."""
        prev = self.last.get(key)
        self.last[key] = (t, dict(counters))
        if prev is None:
            return None, 'first sample'
        pt, pc = prev
        dt = t - pt
        if dt <= 0:
            return None, 'no time passed'
        rates = {}
        for name, value in counters.items():
            delta = value - pc.get(name, value)
            if delta < 0:
                # Counter went backwards: port or rule was recreated. Use
                # this sample as the new starting point.
                return None, 'counter reset'
            rates[name] = delta / dt
        return rates, dt

    def forget(self, key):
        self.last.pop(key, None)


class CongestionDetector:
    """Per-link state machine.

    A link becomes congested after `polls` consecutive samples above the
    threshold, and clears after `polls` consecutive samples at or below
    it. A missing sample changes nothing: the counters keep their values
    until real data arrives (it neither confirms nor clears congestion).
    """

    def __init__(self, threshold, polls):
        self.threshold = threshold
        self.polls = polls
        self.state = {}

    def _get(self, link):
        return self.state.setdefault(link, {'over': 0, 'under': 0, 'congested': False})

    def update(self, link, utilization):
        """Feed one sample. Returns 'detected', 'cleared' or None."""
        s = self._get(link)
        if utilization > self.threshold:
            s['over'] += 1
            s['under'] = 0
            if not s['congested'] and s['over'] >= self.polls:
                s['congested'] = True
                return 'detected'
        else:
            s['under'] += 1
            s['over'] = 0
            if s['congested'] and s['under'] >= self.polls:
                s['congested'] = False
                return 'cleared'
        return None

    def is_congested(self, link):
        return self._get(link)['congested']

    def over_count(self, link):
        return self._get(link)['over']
