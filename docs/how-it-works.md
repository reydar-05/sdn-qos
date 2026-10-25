# How it works

This document explains the whole system step by step: the network, what
the controller measures, how it decides, how it changes the network, how
we measured the result, and what the limits are.

## 1. The problem in one paragraph

Video is played while it is still arriving, so the network must deliver
it steadily. The Internet is best effort: when a link is full, packets
wait in queues (delay and jitter go up) or are dropped (loss). The viewer
sees this as buffering and freezing. Classic QoS is configured by hand on
each device and cannot react to traffic that changes from second to
second. In software defined networking (SDN) one controller sees the whole
network and can change every switch's forwarding rules, so it can notice
congestion and react while the video is playing.

## 2. The network

```
 h1 (video client, 10.0.0.1) ---+          +--- s2 ---+
                                s1         |          s4 --- h2 (video server, 10.0.0.2)
 h3 (background, 10.0.0.3) -----+          +--- s3 ---+

 Path A (default):     s1 - s2 - s4
 Path B (alternative): s1 - s3 - s4
```

- Built by Mininet (`sdn/topology.py`), all values from `config/config.yaml`.
- Four Open vSwitch switches speaking OpenFlow 1.3, in fail-mode secure:
  a switch does nothing by itself; every rule comes from the controller.
- Port numbers are fixed, so OpenFlow port N is always interface sX-ethN:

| Link | Ports |
|---|---|
| s1 to s2 | s1 port 3, s2 port 1 |
| s2 to s4 | s2 port 2, s4 port 2 |
| s1 to s3 | s1 port 4, s3 port 1 |
| s3 to s4 | s3 port 2, s4 port 3 |

Hosts: h1 on s1 port 1, h3 on s1 port 2, h2 on s4 port 1.

The video goes from h2 to h1, so on Path A it leaves s4 towards s2 (link
direction `s4->s2`) and then s2 towards s1 (`s2->s1`). The background
traffic goes from h2 to h3 and always uses Path A, so it competes with the
video on the same links until the controller moves the video.

### Why the loop does not cause a broadcast storm

The four switches form a loop (s1, s2, s4, s3, back to s1). A normal
learning switch floods unknown packets out of every port, so in a loop
they would circle forever. This controller never floods:

1. **Table-miss rule = drop.** A packet that matches no rule is dropped.
2. **ARP is answered by the controller.** Every ARP request is sent to
   the controller, which replies from the host table in the config
   (proxy ARP). Nothing is broadcast.
3. **Explicit paths.** The controller installs a rule for each
   destination host along the chosen path, so every packet has exactly
   one way to go.
4. **Link discovery with LLDP.** Ryu's `--observe-links` sends LLDP
   probes and reports each switch-to-switch link; the controller checks
   them against the config before installing paths.

The Phase 1 verification checked this on the real network: no growing
packet counters on idle links (only the expected LLDP probes).

## 3. The bottleneck and the two queues

Each switch-to-switch link is limited to **10 Mbit/s** with Open vSwitch
QoS of type `linux-htb` (Hierarchical Token Bucket, the Linux traffic
shaper). It is set on both ends of every link, because HTB shapes the
traffic that *leaves* a port. Each port gets two queues:

| Queue | Used by | Guaranteed (min) rate | Priority |
|---|---|---|---|
| q0 | everything else (default) | 4 Mbit/s | 1 (lower) |
| q1 | video and its ping probe | 6 Mbit/s | 0 (higher) |

6 + 4 = 10 Mbit/s, so the guarantees fit the link. When the link is full,
HTB still gives queue 1 its 6 Mbit/s first; the 4 Mbit/s video fits
inside that, so it is not dropped.

Each queue holds **25 packets** (set with the port's `txqueuelen` before
the queue is created). Reason: all Mininet hosts share one Linux kernel.
With a long queue, the kernel slowed the senders down instead of letting
the switch drop packets, which hid the congestion. A short queue makes the
switch behave like a real congested router (Phase 2 and 3 findings,
docs/troubleshooting.md).

Mininet's own `TCLink` bandwidth limit is deliberately **not** used: it
would put a second traffic shaper on the same interfaces and the two would
conflict.

## 4. Recognising the video

The video is a UDP stream on port **5004** (configurable). The controller
installs higher-priority rules that match:

- UDP with destination port 5004, and UDP with source port 5004, between
  the video server h2 and client h1 (both directions of the stream)
- the ICMP ping between h1 and h2, so the ping probe takes the same path
  and queue as the video and measures the delay the video sees

All other IPv4 traffic matches the lower-priority "by destination host"
rules on Path A, in queue 0.

Rule table (higher number wins):

| Priority | Rule | Cookie |
|---|---|---|
| 65535 | LLDP to controller (Ryu topology discovery) | Ryu's |
| 100 | ARP to controller | 0x1 |
| 20 + generation | video and ping probe: path and queue 1 | 0x20 + generation |
| 10 | IPv4 by destination: Path A, queue 0 | 0x10 |
| 0 | anything else: drop | 0x1 |

## 5. Monitoring (what the controller measures)

Every **2 seconds** (`poll_interval_s`) the controller asks every switch
for:

- **Port statistics**: bytes sent per port. The difference between two
  replies, divided by the time between them (taken from the switch's own
  counter clock), gives the throughput of that link direction in Mbit/s.
  Throughput divided by capacity (10 Mbit/s) gives **utilization**.
  Drop counters per port are kept as well.
- **Flow statistics** of the video rules: the video's own rate on each
  switch. This shows which path the video is really using.
- **Queue statistics**: the rate in q0 and q1 of every port.

If a switch does not answer within the timeout, an event `stats_missing`
is logged, its links keep their last values marked "stale", and the round
is skipped for decisions. Every poll is written as one JSON line
(`metrics.jsonl`) and pushed to the Flask backend.

**The controller cannot measure delay, jitter or packet loss of the
video.** OpenFlow counters only count bytes and packets. Those three are
measured on the end hosts (section 9).

## 6. Detecting congestion

A link direction is **congested** when its utilization is above
**0.80** (80%) for **3 polls in a row** (`consecutive_polls`). It is
cleared after 3 polls in a row below the threshold. Requiring several
polls stops a single short burst from triggering anything. With 2 s polls,
detection takes about 6 s, which matches the measured 5.8 to 6.0 s.

Logged events: `congestion_detected`, `congestion_cleared` (with link,
utilization, and whether it is on the video path).

## 7. Deciding to reroute (qos mode only)

When a link on the video's current path is congested, the controller
checks, in order:

1. Fewer than `max_reroutes_per_run` (4) reroutes so far.
2. No reroute in the last `cooldown_s` (20 s).
3. The previous reroute was confirmed by all switches.
4. Fresh statistics exist for the other path.
5. **Admission check**: the other path's current load plus the video's
   measured rate, divided by capacity, stays below the threshold. Example
   from the experiment: Path B load 0.0 + 4.12 / 10 = 0.41, below 0.80,
   so the move is allowed.

If any check fails, nothing changes and a `reroute_skipped` event with the
reason is logged once. These rules (several polls, cooldown, maximum,
admission check) are the **anti-flap** protection: the video cannot bounce
between paths.

The video is not moved back to Path A automatically when Path A clears.
That keeps the logic simple and makes flapping impossible; the cost is
that the video stays on Path B until the next run.

## 8. Changing the path (make-before-break)

1. Install the video rules for the new path with a **higher priority**
   and a **new cookie** (a tag on each rule). Packets switch to the new
   rules as soon as they exist on a switch, so nothing is dropped in
   between.
2. Send an OpenFlow **barrier** to each switch and wait for the reply
   (the switch confirms it has applied everything before it).
3. Delete the old rules by their cookie, then another barrier.
4. Log `reroute_confirmed` with the time from first rule to last barrier
   reply. Measured: **11.1 ms** on average (9.1 to 14.4).

The new rules also carry `set_queue:1` on every switch-to-switch hop, so
the video uses the guaranteed queue on Path B too.

## 9. What is measured where

| Quantity | Source | How |
|---|---|---|
| Link throughput, utilization | controller | port statistics every 2 s |
| Video rate per switch / path | controller | flow statistics of the video rules |
| Queue rates | controller | OpenFlow queue statistics |
| Congestion time, reroute time, rule install time | controller | events |
| Video received rate, packet loss, jitter | end host h1 | iperf3 receiver report, every second |
| Background received rate and loss | end host h3 | iperf3 receiver report |
| Delay | end host h1 | `ping -D -O -i 0.2` to h2 (the probe follows the video path); `-O` also counts lost probes |
| Drops per queue | Linux kernel | `tc -s class show` on s4's ports, before and after the load |
| Stalls, stall time, startup delay | playout buffer MODEL | fed by the received bits per second (section 10) |

## 10. The playout buffer model (not a real player)

`sdn/playout_model.py` turns "how many video bits arrived each second"
into what a simple player would do:

- Playback starts after 2 s of video is buffered.
- Playing uses 1 s of video per second.
- If the buffer runs empty the player stalls (a buffering event) until
  1 s of video is buffered again.
- Lost packets add nothing to the buffer.

It is labelled "model" everywhere because no real video is decoded. It
shows the effect of lost throughput on a viewer, not picture quality.

Why iperf3 instead of a real video: the controller recognises video by
port, not by content, so a constant 4 Mbit/s UDP stream on the video port
is treated exactly like a live UDP video stream. iperf3 knows exactly
what it sent, so loss and jitter are exact, and every run is identical,
which makes the comparison fair.

## 11. The two modes

| | baseline | qos |
|---|---|---|
| Forwarding | static, Path A | Path A, video moved when congested |
| Queue for video | q0 (same as everything) | q1 (guaranteed 6 Mbit/s) |
| Monitoring and congestion events | yes | yes |
| Reroute | never | yes, with the anti-flap rules |

The same network, the same 10 Mbit/s shaping and the same traffic are used
in both modes; only the controller's behaviour changes. For testing, the
environment variables `SDN_QOS_REROUTE=0` or `SDN_QOS_QUEUES=0` switch one
mechanism off in qos mode.

## 12. The experiment

`scripts/run_experiments.sh` runs 12 runs of 60 s, without anyone at the
keyboard (about 18 minutes):

- Cases: baseline and qos, each with light (3 Mbit/s) and heavy
  (9 Mbit/s) background, 3 runs each, interleaved (run 1 of every case,
  then run 2...) so slow changes on the VM affect every case equally.
- Each run starts from scratch: clean Mininet, fresh Ryu, new network.
- Timeline: video from 0 to 60 s; background from 10 to 50 s.
- Measurement window: 20 to 50 s ("steady": the 10 s after the load
  starts are left out so the reaction itself does not dominate the mean).
- Validity check: a run counts only if both senders really sent at least
  97% of the asked rate (otherwise the VM, not the network, was the
  bottleneck). All 12 runs were valid.
- Light load: 4 + 3 = 7 Mbit/s on a 10 Mbit/s link (72% utilization),
  below the threshold. Heavy load: 4 + 9 = 13 Mbit/s, over capacity.

## 13. Results and how to read them

Measured means (heavy load, 20 to 50 s), full table in the README and
`docs/results/20261025-211618/`:

- Baseline: the video and the background share one queue on a link that
  is 30% oversubscribed. The video lost 36.2% of its packets (19 to 45%
  between runs), ping delay rose to 31.4 ms (the queue is full), and the
  buffer model stalled 6.3 times.
- QoS: congestion detected 6.0 s after the load started, video moved to
  Path B 0.01 s later, rules confirmed in 11.1 ms. From then on: 0% video
  loss, 0.074 ms jitter, 0.115 ms ping, no stalls. Path A carried only the
  background (93% utilization), Path B the video (41%).
- The background traffic also did better with QoS (9.0 vs 7.16 Mbit/s
  received), because after the reroute the two flows use different
  paths. So the gain for video did not come at the cost of other traffic.
- Kernel counters: in qos heavy runs, about 1660 packets were dropped in
  queue 0 on s4 to s2, all in the 6 s before the reroute and all
  background traffic. Queue 1 (video) had 0 drops in every run.
- Light load: nothing to fix. Both modes 0% loss, no reroute. The
  0.17 vs 0.11 ms ping difference is far below a millisecond and should
  not be read as a QoS gain.
- A separate single run in Phase 3 with **only** the priority queue (no
  reroute) also kept the video at 0% loss: the queue alone protects the
  video, the reroute additionally gives the other traffic its full rate.

## 14. Live lab and dashboard

```
Ryu controller --(metrics, events, heartbeat; HTTP POST)--> Flask :5000 --(JSON)--> dashboard :5173
lab script (iperf3 + ping on the hosts) --(host samples; HTTP POST)--^
```

- `scripts/start_lab.sh` starts Flask and the dashboard, then (with sudo)
  `sdn/lab.py`: cleans Mininet, starts Ryu, builds the network and queues,
  and offers a menu to switch the video and background traffic on and off.
- The lab reads the iperf3 receivers' and ping's output line by line and
  sends one end-host sample per second to Flask, so the dashboard can show
  live loss, jitter and delay, labelled as end-host data.
- Flask keeps the latest data in memory and on disk (`results/live/`) and
  serves it read-only to the dashboard. It reports the controller as not
  reachable after 8 s without data, and the dashboard then shows an error
  state instead of old numbers.
- DEMO MODE uses invented data from `frontend/src/demo/demoData.js`, with
  a DEMO DATA stamp everywhere; it is used for the public Vercel site.

## 15. Limitations

- Emulation on one VM: all hosts share one kernel and CPU; absolute
  numbers are not those of real hardware.
- Constant bitrate UDP video, not real encoded video: no MOS, SSIM or
  VMAF, no keyframe bursts, no adaptive bitrate (DASH over TCP would
  react differently).
- Buffering comes from a model.
- Polling every 2 s plus 3 polls means about 6 s to react. A shorter
  poll interval is one config value, but was not measured.
- The QoS gain needs a free alternative path. If both paths were full,
  only the priority queue could protect the video.
- One video flow, two paths, fixed capacities: the design is not tested
  at larger scale.
- The video does not move back to Path A automatically.
- 3 runs per case: consistent differences, but not tight statistical
  confidence intervals.
