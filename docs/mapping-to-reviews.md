# Mapping to the review decks

What the two review decks promised, and where the project meets it.
Decks (read with python-pptx): `docs/requirements/sdn-qos-video-streaming.pptx`
(Review 1) and `docs/requirements/SDN-QoS-Review2.pptx` (Review 2).
Results quoted are from experiment 20261025-211618 (heavy load, mean of 3
runs, 20 to 50 s), see `docs/results/20261025-211618/`.

Status: **Met**, **Partly met** (met with a stated difference), or
**Different** (replaced, with the reason).

## Objectives (Review 2 slide 4, Review 1 slide 4)

| # | Objective | Status | Where and evidence |
|---|---|---|---|
| R2-1 / R1-O1 | Monitor delay, jitter, packet loss and link usage from the controller | Partly met | Link usage, throughput and drop counters: controller, every 2 s (`sdn/controller.py`, `sdn/monitor.py`). Delay, jitter and loss: measured on the end hosts (ping, iperf3) and shown next to the controller data, because OpenFlow counters cannot measure them. Each value is labelled with its source on the dashboard. |
| R2-2 / R1-O2 | Detect when a link carrying video becomes congested | Met | Threshold 0.8 for 3 consecutive polls; `congestion_detected` 5.8 to 6.0 s after the load started, in every heavy run; no false detection at 72% (light load). |
| R2-3 / R1-O3 | Identify video traffic and separate it from ordinary traffic | Met | Video matched by UDP port 5004 (source or destination) with higher-priority rules; other traffic by destination host. Verified with flow dumps (Phase 1 and 3). |
| R2-4 | Move the video flow to a free path and to a priority queue | Met | Reroute A to B after 6.04 s, rules confirmed in 11.1 ms (make-before-break); video in queue 1 (min 6 Mbit/s) on every hop, 0 kernel drops in queue 1. |
| R1-O4 | Allocate bandwidth dynamically and reroute when a path degrades | Partly met | Rerouting is dynamic. Bandwidth is reserved with a fixed guaranteed rate for the video queue (6 Mbit/s, set in config), not recomputed at run time. |
| R2-5 / R1-O5 | Reduce packet loss, delay (and jitter) and buffering events | Met (in this setup) | Video loss 36.2% to 0%, ping 31.4 ms to 0.115 ms, jitter 0.566 to 0.074 ms, stalls (model) 6.3 to 0. Under light load there was nothing to reduce. |
| R2-6 | Compare against a plain network with no QoS control | Met | Baseline mode: same network, same shaping and traffic, static Path A, one queue. 12 runs, all valid. |
| R1-O6 | Improve measured video QoE, not just network numbers | Partly met | QoE indicators from the playout buffer model (startup delay, stall count, stall time), fed by measured data. No perceptual scores (MOS, SSIM, VMAF): no real video is decoded. |

## Research gaps the project said it addresses (Review 2 slide 6)

| Gap and promise | Status | Notes |
|---|---|---|
| 1. "Checks run once a second or slower, so reaction is late" / "We poll switches often" | Partly met | Polling interval is one config value (`poll_interval_s`); the experiments used **2 s**, which is not faster than the once-a-second checks the slide criticises. With 3 polls required, reaction took about 6 s. A 1 s interval was not measured. Say this honestly if asked. |
| 2. "Good QoS numbers do not always mean better video" / "We record buffering at the player" | Partly met | Buffering is recorded from a playout buffer model at the client side, fed by what the client really received; not from a real player. |
| 3. "Many works pick a better path but reserve no bandwidth" / "We reroute and also use a priority queue" | Met | Both, together: reroute plus queue 1 with a guaranteed 6 Mbit/s. A single Phase 3 run with the queue only also protected the video; the reroute additionally gave the background its full rate (9.0 vs 7.16 Mbit/s). |
| 4. "Thresholds suit one setup" / "All thresholds in one small config file" | Met | `config/config.yaml`: threshold, polls, cooldown, poll interval, capacities, queue rates, ports, traffic rates. The dashboard shows them read-only. |

## How it works (Review 2 slide 8, Review 1 slide 7)

| Step | Status | Where |
|---|---|---|
| 1. Mininet builds a small network with two paths to the server | Met | `sdn/topology.py`: Path A s1-s2-s4, Path B s1-s3-s4 |
| 2. Ryu connects and learns the topology | Met | LLDP link discovery (`--observe-links`), checked against the config |
| 3. Video recognised by its port number | Met | UDP 5004 |
| 4. Controller reads port statistics every few seconds | Met | every 2 s, plus flow and queue statistics |
| 5. Over the threshold: move the flow and use the priority queue | Met | with admission check, cooldown and maximum (anti-flap) |
| 6. Monitoring continues, change checked in the next round | Met | `reroute_confirmed` by barrier; following polls show the video rate on s3 and none on s2 |
| Controller modules: Monitoring and Statistics, QoS Decision, Flow Rule Enforcement | Met | `on_port_stats` / `on_flow_stats` / `on_queue_stats`; `maybe_reroute`; `reroute` + `install_video_rules` in `sdn/controller.py` |

Review 2 slide 7 ("System Architecture") has only drawn shapes and no
text; the README's Mermaid diagram is the project's architecture.

## Tools (Review 2 slide 9)

| Promised | Status | Notes |
|---|---|---|
| Mininet | Met | 2.3.0 |
| Open vSwitch | Met | 2.17.12, OpenFlow 1.3 |
| Ryu (Python) | Met | 4.34, with documented fixes for Python 3.10 (docs/installation-guide.md) |
| tc / HTB for the two queues | Met | through Open vSwitch `linux-htb` QoS (which creates the tc HTB classes); kernel tc counters read for drops |
| VLC or DASH client to play video | Different | Replaced by a 4 Mbit/s iperf3 UDP stream on the video port plus the playout buffer model. Reasons: the controller classifies by port, so it treats both the same; iperf3 gives exact loss and jitter and identical runs; decoding video on the shared VM would distort timing. |
| iperf3 for background traffic | Met | 3.9; also used for the video stream |

## Test plan (Review 2 slide 9)

| Promised | Status | Notes |
|---|---|---|
| Case 1: plain network, no QoS control | Met | baseline mode |
| Case 2: same network, our controller on | Met | qos mode |
| Both with light and heavy traffic | Met | 3 and 9 Mbit/s background |
| Record delay, jitter, loss, buffering | Met | ping, iperf3, playout model (labelled) |
| Compare the two cases and plot results | Met | `docs/results/`, README table, dashboard Experiments page (bar charts and per-second charts) |

## Expected results (Review 2 slide 10, Review 1 slide 7)

| Expected | Measured (heavy load) | Status |
|---|---|---|
| Lower packet loss on the video flow | 36.2% to 0% | Met |
| Steadier delay and jitter | ping 31.4 to 0.115 ms, jitter 0.566 to 0.074 ms | Met |
| Fewer buffering events | 6.3 to 0 (model) | Met, from the model |
| Other traffic still works normally | background 7.16 to 9.0 Mbit/s received, loss 20.5% to 0% | Met (even improved, because the flows were split) |
| Better bandwidth utilisation (R1) | after the reroute both paths are used (A 93%, B 41%) instead of one oversubscribed path | Met in this setup |
| Higher, steadier QoE (R1) | no stalls in the model; no perceptual score | Partly met |

## Scope items in the decks that are not built

- **Reinforcement learning routing** (Review 1 literature, Al Jameel et
  al.): literature only. The project rules exclude ML and RL.
- **DASH-assisting network elements and per-client bitrate control**
  (Kleinrouweler et al., SDNDASH): not built; there is no adaptive player.
- **Perceptual quality scores** (MOS, SSIM, VMAF): not measured.
