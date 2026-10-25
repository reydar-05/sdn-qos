# 5 minute faculty demo

One person drives, one person talks (or one person does both). Practise it
once end to end before the real demo.

## Before the faculty arrive (10 minutes earlier)

1. Start the VM, open a terminal:
   ```
   cd ~/sdn-qos
   bash scripts/start_lab.sh
   ```
   Enter the sudo password. Wait for `=== Lab ready in QOS mode`
   (about 20 s). Leave this terminal visible: it is the traffic menu.
2. Open Firefox on the VM: http://127.0.0.1:5173. Click **LIVE LAB**
   (top right). The banner must be **green** ("controller connected").
3. Type `v` in the lab terminal (video on), so the end-host charts have
   data. Check the Overview page: Path A, no congestion, video about
   4 Mbit/s, video loss 0%.
4. Open a second browser tab on **Experiments** (LIVE LAB) and check it
   shows experiment 20261025-211618 with 12 valid runs.
5. Make the browser window large, zoom to 90% if the charts are cramped.
6. **If you rehearsed with `a` in this lab session, restart it now** (`q`,
   then `bash scripts/start_lab.sh`). The controller never moves the video
   back to Path A by itself, so after one reroute the video stays on
   Path B and a second scenario shows no reroute. Overview must say
   **Path A** before you start.

## The demo

### 0:00 to 0:45: the problem and the idea (Overview page)

Say:
> "Video is played while it arrives, so congestion shows up immediately
> as loss, delay and buffering. A normal network cannot react. With SDN,
> one controller sees every link and can change the paths. Our Ryu
> controller polls the switches every 2 seconds, detects a congested
> link, and moves the video to a free path and into a priority queue."

Point at: the controller tile (4/4 switches connected), the video path
tile (Path A), the link utilization table.

### 0:45 to 1:30: the network (Topology page)

Say:
> "Mininet with four Open vSwitch switches. The video goes from server h2
> to client h1. Path A through s2 is the default, Path B through s3 is the
> alternative. Each link is limited to 10 Mbit/s with two queues: a
> priority queue for video with 6 Mbit/s guaranteed, and a default queue.
> There is a loop, but no broadcast storm: the controller never floods, it
> answers ARP itself and installs every path explicitly."

### 1:30 to 3:00: live congestion and reroute (QoS monitoring page)

Type `a` in the lab terminal (auto scenario). Switch to the **QoS
monitoring** page.

Say while it runs:
> "The video is running at 4 Mbit/s. At 10 seconds we add 9 Mbit/s of
> background traffic on the same path: 13 Mbit/s on a 10 Mbit/s link."

At about 10 s: Path A utilization jumps to 100% (above the dashed 0.8
threshold).

> "The controller needs three polls in a row above 80% so a short burst
> does not trigger it. That takes about 6 seconds."

At about 16 s: the vertical line "to Path B" appears; the video flow rate
moves from s2 to s3.

> "There: congestion detected and the video moved to Path B. The new rules
> are installed before the old ones are deleted, so no packet is lost
> during the switch. Look at the end-host charts: video loss stays at 0,
> delay stays below a millisecond."

Open **Event logs** for a moment:
> "congestion_detected, reroute, reroute_confirmed: the switches confirmed
> the new rules in about 10 milliseconds."

### 3:00 to 4:15: the measured comparison (Experiments page)

Say:
> "A live run is one example, so we also ran a proper experiment:
> baseline without QoS against our controller, with light and heavy
> background traffic, 3 runs each, 12 runs in total, all valid."

Point at the bar charts (heavy load):
> "Without QoS the video lost 36% of its packets, ping went to 31
> milliseconds and our buffer model stalled 6 times. With QoS: 0% loss,
> about 0.1 milliseconds, no stalls. The background traffic did better
> too, 9 instead of 7 Mbit/s, because the two flows now use different
> paths."

Scroll to the per-second charts on QoS monitoring (Recorded section) if
there is time: the orange baseline line collapses at 10 s, the blue QoS
line stays flat.

### 4:15 to 5:00: honest limits and conclusion

Say:
> "Limits: this is an emulation on one VM, the video is a constant-rate
> UDP stream from iperf3 rather than real encoded video, and buffering
> comes from a model fed by the measured data. Delay, jitter and loss are
> measured on the hosts; the controller measures link load. And the gain
> needs a free second path. Within that setup, the controller removed the
> video loss and the delay completely and did not hurt other traffic."

Type `q` in the lab terminal afterwards (or leave it running for
questions).

## If something goes wrong

| Problem | What to do |
|---|---|
| Banner red "backend not reachable" | `bash scripts/stop_lab.sh`, then `bash scripts/start_lab.sh` (20 s). |
| Banner red "controller not sending data" right after start | Wait until the terminal says "Lab ready". If it stays red, `q` and start again. |
| The lab stops with an error at start | Run `bash scripts/stop_lab.sh` (it also cleans Mininet), then start again. |
| No reroute after 15 s in the auto scenario | The video was probably already on Path B from an earlier run (check Overview). Otherwise check the terminal says QOS mode (not baseline) and type `s` for status. Show the Experiments page and the recorded per-second charts instead: they show the same behaviour from the real experiment. |
| Nothing works at all | Click **DEMO MODE**: it walks through the same story with clearly labelled sample data and needs no lab. Say that it is sample data. The real numbers are in the README and `docs/results/`. |

## Optional extra (if they ask to see the baseline live)

Type `m` in the lab terminal: it restarts everything in baseline mode
(about 20 s). Then `a`. The video loss chart climbs to about 40% and the
delay to about 30 ms during the load, and no reroute happens. Type `m`
again to go back to QoS mode.
