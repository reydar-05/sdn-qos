"""
Playout buffer MODEL (not a real video player).

Turns the measured per-second received video data (iperf3 receiver
report) into estimated buffering events, the way a simple video player
would behave:

- The player needs startup_buffer_s seconds of video before it starts.
- While playing it uses 1 second of video per second.
- Each second the network adds (received bits / video bitrate) seconds
  of video. Packets that were lost add nothing.
- If the buffer runs empty, playback stalls (a buffering event) until
  resume_buffer_s seconds of video have arrived again.

Assumption to state whenever these numbers are shown: lost data counts
as missing video (as if the player had to wait for it), so this measures
the effect of lost and late throughput, not picture quality.
"""


def simulate(received_bits_per_interval, interval_s, bitrate_bps,
             startup_buffer_s=2.0, resume_buffer_s=1.0):
    """Return a dict with startup delay, stall count, stall time and the
    buffer level after every interval (seconds of video)."""
    buffer_s = 0.0
    playing = False
    started_at = None
    stalls = 0
    stall_time = 0.0
    levels = []
    t = 0.0
    for bits in received_bits_per_interval:
        added = bits / bitrate_bps
        before = buffer_s
        buffer_s += added
        t += interval_s
        if not playing:
            needed = startup_buffer_s if started_at is None else resume_buffer_s
            # small tolerance: a 4 Mbit/s stream rarely delivers exactly
            # 4,000,000 bits in one second
            if buffer_s >= needed - 1e-3:
                playing = True
                if started_at is None:
                    # moment inside this interval when the threshold was reached
                    frac = (needed - before) / added if added > 0 else 1.0
                    started_at = round(t - interval_s + min(max(frac, 0.0), 1.0) * interval_s, 3)
            elif started_at is not None:
                stall_time += interval_s
        else:
            if buffer_s >= interval_s:
                buffer_s -= interval_s
            else:
                # Plays what is left, then stalls for the rest of the interval.
                stall_time += interval_s - buffer_s
                buffer_s = 0.0
                playing = False
                stalls += 1
        levels.append(round(buffer_s, 3))
    return {
        'startup_delay_s': started_at,
        'stall_count': stalls,
        'stall_time_s': round(stall_time, 3),
        'buffer_levels_s': levels,
        'model': 'playout buffer model (startup %.1f s, resume %.1f s)'
                 % (startup_buffer_s, resume_buffer_s),
    }
