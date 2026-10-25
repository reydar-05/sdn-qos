# Requirements summary (from the two review decks)

Source files, read with python-pptx:
- `docs/requirements/sdn-qos-video-streaming.pptx` (Use Case Review 1, 7 slides with speaker notes)
- `docs/requirements/SDN-QoS-Review2.pptx` (Use Case Review 2, 10 slides)

This file lists what the decks promise, so the finished project can be
checked against it (see docs/mapping-to-reviews.md at the end).

Note: slide 7 of Review 2 ("System Architecture") only contains drawn
shapes with no text, so the architecture below comes from the "How It
Works" slide (Review 2, slide 8) and the framework slide (Review 1,
slide 7).

## Problem
- Video plays while it is still arriving, so any break is visible at once.
- The Internet is best-effort: no guarantee on delay, bandwidth or delivery.
- Congestion makes delay, jitter, packet loss and throughput all worse.
- The viewer sees buffering (rebuffering), freezing, long startup delay and poor quality.
- Traditional QoS (static DiffServ / IntServ, per-device CLI) is set by hand,
  has no network-wide view and cannot follow changing traffic.

## Why SDN
- The control plane is separated from the data plane, giving one controller a network-wide view.
- The controller is programmable (Ryu) and reads OpenFlow port and flow counters.
- Closed loop: measure, decide, enforce (flow rules), re-measure, repeated while the video plays.

## Objectives
Review 2 (the current one):
1. Monitor delay, jitter, packet loss and link usage from the controller.
2. Detect when a link carrying video becomes congested.
3. Identify video traffic and separate it from ordinary traffic.
4. Move the video flow to a free path and to a priority queue.
5. Reduce packet loss, delay and the number of buffering events.
6. Compare the result against a plain network with no QoS control.

Review 1 adds: allocate bandwidth dynamically (O4) and improve measured
video QoE, not just raw network numbers (O6).

Important for honesty (CLAUDE.md): the controller can only measure link
usage, throughput and drop counters. Delay, jitter and loss are measured
at the end hosts (ping, iperf3). Objective 1 will be reported that way.

## Research gaps the project claims to address (Review 2, slide 6)
1. Poll switches often so congestion is caught early (configurable poll interval).
2. Record buffering at the player, not only delay and loss.
3. Reroute and also use a priority queue to reserve bandwidth.
4. All thresholds in one small config file.

## Architecture and workflow (Review 2 slide 8, Review 1 slide 7)
1. Mininet builds a small network with two paths to the server.
2. The Ryu controller connects and learns the topology.
3. Video traffic is recognised by its port number.
4. The controller reads port statistics every few seconds.
5. If a link passes the threshold, the video flow is moved to the other path and a priority queue.
6. Monitoring continues and the change is checked in the next round.

Controller modules: Monitoring and Statistics, QoS Decision (detect
congestion, choose path and queue), Flow Rule Enforcement (install or
update OpenFlow rules). Data plane: video clients, OpenFlow switches,
streaming server.

## Tools promised
- Mininet (network), Open vSwitch (OpenFlow switches), Ryu in Python (controller)
- tc / HTB for the two queues (done through OVS linux-htb QoS)
- VLC or a DASH client to play video
- iperf3 for background traffic

## Test plan promised
- Case 1: plain network, no QoS control.
- Case 2: same network, our controller on.
- Run both with light and heavy traffic.
- Record delay, jitter, loss and buffering.
- Compare the two cases and plot results.

## Expected results promised
- Lower packet loss on the video flow.
- Steadier delay and jitter.
- Fewer buffering events.
- Other traffic still works normally.
- (Review 1) Better bandwidth utilisation, higher and steadier QoE.

## Known differences to decide and document (to be confirmed in later phases)
- Video player: the decks name VLC or a DASH client. CLAUDE.md fixes the
  video flow as iperf3 UDP on port 5004. Buffering will therefore come
  from a playout buffer model fed by the measured per-interval received
  data, clearly labelled as a model and not a real player.
- QoE scores such as MOS, SSIM and VMAF (Review 1) are out of scope; no
  real decoded video is measured.
- Reinforcement learning (Review 1 literature) is literature only;
  CLAUDE.md forbids ML/RL in the build.
- "Allocate bandwidth dynamically" is done as a fixed guaranteed rate for
  the video queue, chosen in config, plus dynamic rerouting.
