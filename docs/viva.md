# Viva preparation

Short answers you can say aloud. Numbers are from experiment
20261025-211618 (heavy load, mean of 3 runs) unless stated otherwise.
For the full explanation see docs/how-it-works.md.

## The project in 30 seconds

> We built a small SDN in Mininet with four Open vSwitch switches and two
> paths between a video server and a client. A Ryu controller polls the
> switches every 2 seconds and computes the load on every link. When the
> link carrying the video stays above 80% for three polls, it moves the
> video to the other path and into a priority queue with a guaranteed
> rate. Under heavy load, video loss went from 36% to 0% and ping delay
> from 31 ms to 0.1 ms, and the other traffic also got more throughput.

## Basics

**What is SDN?**
The control plane (deciding where packets go) is moved out of the
switches into a central controller. Switches only forward according to
rules the controller installs. The controller sees the whole network and
can be programmed.

**What is OpenFlow? Why version 1.3?**
The protocol between controller and switches: install rules (match plus
actions), read statistics, receive packets. 1.3 has queue selection
(`set_queue`), barriers, cookies and good Ryu support.

**What do Mininet, Open vSwitch and Ryu each do?**
Mininet creates virtual hosts and links on one Linux machine. Open vSwitch
is the software switch (real OpenFlow switch). Ryu is a Python framework
for writing the controller.

**What is a flow rule?**
A match (for example "UDP, destination port 5004, from 10.0.0.2"), a
priority, and actions (for example "set queue 1, output port 3"). The
highest-priority matching rule wins.

## Design

**How do you recognise video?**
By port: UDP port 5004, source or destination, between the video server
and client. The controller installs higher-priority rules for it.

**The topology has a loop. Why no broadcast storm?**
Nothing is ever flooded. Unknown packets are dropped (table-miss rule),
ARP requests go to the controller, which answers them from the host table,
and every path is installed explicitly. Links are discovered with LLDP.

**How is utilization computed?**
Port statistics give bytes sent. (bytes now minus bytes before) × 8,
divided by the seconds between the two replies, gives bit/s. Divided by
the link capacity (10 Mbit/s) gives utilization.

**Why threshold 0.8 and 3 consecutive polls?**
0.8 leaves headroom before the link is full and queues build up. Our
light load ran at 72% without any false alarm. Three polls in a row stop a
single burst from causing a reroute. Both are one value in
`config/config.yaml`.

**How do you avoid flapping (moving back and forth)?**
Several polls before acting, a 20 s cooldown after a reroute, at most 4
reroutes per run, the previous reroute must be confirmed, an admission
check (the new path must stay below the threshold with the video added),
and no automatic move back.

**What is the admission check?**
Load of the other path plus video rate divided by capacity must be below
the threshold. In the experiment: 0.0 + 4.12 / 10 = 0.41, so it moved.

**What if both paths are congested?**
The admission check fails, the controller logs `reroute_skipped` with
reason `no_better_path` and leaves the path alone. The priority queue
still protects the video on its current path.

**What is make-before-break?**
Install the new rules first with a higher priority and a new cookie,
confirm with a barrier, then delete the old rules by cookie. Packets
always have a valid rule, so the switch itself does not lose them.
Measured install time: 11.1 ms on average.

**What is a barrier, and a cookie?**
A barrier request makes the switch reply only after it has applied all
earlier messages, so we know the rules are active. A cookie is a number
tag on a rule, so we can delete exactly one generation of rules.

**Why does the video not move back to Path A?**
Simplicity and no flapping. The cost: it stays on Path B until the next
run. Moving back with hysteresis is future work.

**What happens if a switch does not answer?**
`stats_missing` is logged, its links keep the old values marked stale, and
no decision is made on stale data.

**Is the controller a single point of failure?**
Yes, in this design. The switches are in fail-secure mode, so they keep
the installed rules if the controller stops; traffic continues on the
current paths, but nothing reacts to congestion. Real deployments use
several controllers.

## Queues

**How are the queues made?**
Open vSwitch QoS of type `linux-htb` on both ends of every switch link:
max 10 Mbit/s, queue 0 (default, min 4 Mbit/s) and queue 1 (video, min
6 Mbit/s, higher priority). The controller's `set_queue:1` action puts
video packets in queue 1.

**Why not Mininet's TCLink bandwidth?**
It would put a second traffic shaper on the same interfaces as the OVS
one, and the two conflict.

**Why only 25 packets per queue?**
All Mininet hosts share one kernel. With long queues the kernel slowed the
senders down instead of letting the switch drop packets, which hid the
congestion. A short queue makes the switch drop like a real congested
router. We also check that every sender really sent at least 97% of its
rate, otherwise the run is invalid.

**Why is the baseline ping exactly about 31 ms?**
In the baseline the shared queue is always full: 25 packets × 1500 bytes
× 8 bits = 300,000 bits, which takes 30 ms to send at 10 Mbit/s. That is
the queueing delay every packet waits.

**Does the queue alone help, or only the reroute?**
A single Phase 3 test with only the priority queue (no reroute) also kept
the video at 0% loss and 0.11 ms ping. So the queue protects the video;
the reroute additionally lets the background traffic use the other path,
which is why it received 9.0 instead of 7.16 Mbit/s. (Single run, not
part of the 3-run experiment.)

## Measurement

**Can the controller measure delay, jitter and loss?**
No. OpenFlow counters only count bytes and packets per port, flow and
queue. Delay, jitter and loss are measured on the end hosts: ping for
delay, the iperf3 receiver for loss and jitter. The dashboard labels every
number with its source.

**Why iperf3 and not a real video?**
The controller classifies by port, not content, so a constant 4 Mbit/s
UDP stream on the video port gets exactly the same treatment as a live UDP
video. iperf3 knows what it sent, so loss and jitter are exact, and every
run is identical, which makes the comparison fair. Limitation: no picture
quality scores and no adaptive bitrate.

**How do you get buffering without a player?**
A playout buffer model: playback starts with 2 s buffered, uses 1 s of
video per second, stalls when empty and resumes at 1 s. It is fed by the
video bits really received each second. It is labelled as a model
everywhere.

**How was the experiment designed?**
Baseline and QoS, light (3 Mbit/s) and heavy (9 Mbit/s) background, 3 runs
each = 12 runs of 60 s, interleaved, each from a fresh network and
controller. Background from 10 to 50 s; numbers from 20 to 50 s. A run is
valid only if both senders sent at least 97% of the asked rate. All 12
were valid.

**Why leave out 10 to 20 s?**
That is when the controller is still detecting and reacting (about 6 s).
The steady window shows the state after the reaction. The whole load
period is also reported (for example background loss 5.3% in QoS over
10 to 50 s, all before the reroute).

**Why does the baseline loss vary so much (19 to 45%)?**
Video and background share one queue and the split of the drops between
the two flows is not stable from run to run. The QoS runs had 0% in all
three.

## Results

**What did QoS improve?**
Heavy load: video loss 36.2% to 0%, jitter 0.566 to 0.074 ms, ping
31.4 to 0.115 ms (58 lost probes to 0), stalls in the model 6.3 to 0,
background received 7.16 to 9.0 Mbit/s.

**What did it not improve?**
Light load: nothing needed fixing; both modes had 0% loss and no reroute.
The small ping difference there (0.17 vs 0.11 ms) is not a meaningful
gain. And reaction is not instant: about 6 s to detect, during which the
background lost packets.

**How fast is the reaction?**
Congestion detected 6.0 s after the load started (3 polls × 2 s),
reroute in the same stats round, rules confirmed in 11.1 ms.

**Is 3 runs enough?**
Enough to show a large and consistent difference (0% in every QoS run vs
19 to 45% loss in every baseline run). Not enough for tight confidence
intervals; more runs would be the next step.

## Limitations and future work

Limitations: emulation on one VM; constant bitrate UDP instead of real
video; buffering from a model; 2 s polling (about 6 s reaction); needs a
free second path; one video flow and two paths only; no automatic move
back; 3 runs per case.

Future work: shorter polling or sFlow sampling for faster detection;
moving back with hysteresis; several video flows and more paths; a real
player (DASH) and perceptual quality scores (VMAF); OpenFlow meters for
per-flow rate limits; more runs and confidence intervals.

**Why no machine learning?**
Out of scope for the project. A simple threshold rule is explainable and
enough to show the effect; learning-based routing is in the literature
review only.

## Implementation questions

**Where is the decision made in the code?**
`sdn/controller.py`: statistics in `on_port_stats`, `on_flow_stats`,
`on_queue_stats`; decision in `maybe_reroute`; enforcement in `reroute`
and `install_video_rules`. Congestion state in `sdn/monitor.py`
(`CongestionDetector`).

**How does the dashboard get data?**
Ryu pushes every poll and event to a Flask backend on localhost (HTTP
POST). The lab script pushes the end-host samples. The React dashboard
reads Flask's JSON API. If Flask or the controller is not reachable, LIVE
mode shows an error, never fake data. DEMO mode uses one clearly labelled
sample file.

**How is it kept safe?**
Everything binds to 127.0.0.1; the OpenFlow port is never exposed. Flask
accepts pushed data only from this machine, supports a token and a CORS
allowlist, and refuses tunnelled requests without a token. The public
Vercel site is static and only shows demo data.

**How was it tested?**
Unit tests for monitoring, the buffer model, the parsers, the backend API
and the frontend demo data; verification scripts on the real network for
each phase (11/11, 12/12, 29/29 checks); the 12-run experiment; and a
live end-to-end run (every controller record reached the dashboard).
