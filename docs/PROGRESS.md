# Progress log

Running log of what has been done, tested, and left open. Read this
first in every new session. Update it at the end of every phase.

## Phase 0: Environment setup - DONE (2026-10-25)

### Done
- Inspected the VM: Ubuntu 22.04.5 LTS, VMware guest, 4 cores, 5.8 GiB
  RAM, ~24 GiB disk free.
- Installed system packages: python3.10-venv/pip/dev, mininet (2.3.0),
  openvswitch-switch (2.17.12, service enabled+active), iperf3,
  net-tools, ffmpeg, Node.js LTS (v24.22.1) via NodeSource.
- Created `.venv` and installed Ryu 4.34, Flask 3.1.3, flask-cors,
  requests, python-pptx - with 3 real Python-3.10 compatibility fixes
  (setuptools pin, eventlet pin at 0.33.3 instead of the commonly
  suggested 0.30.2, and a one-line patch to Ryu's `wsgi.py`). Full
  diagnosis in docs/troubleshooting.md.
- Created the repo layout (`frontend/ backend/ sdn/ config/ scripts/
  results/ docs/`).
- Wrote and ran all verification scripts in `scripts/`. Every check
  passed with real, measured output (not assumed):
  - `inspect_environment.sh` - all tools present and correct versions
  - `verify_environment.sh` - OVS, iperf3, tc/HTB, a hand-built
    Vite+React build, Flask hello-world - all pass
  - `test_mininet.sh` - `sudo mn --test pingall`, 0% dropped
  - `verify_controller.sh` - Ryu + Mininet + OVS OpenFlow 1.3, switch
    connected (dpid=1), 0% dropped through the controller
  - `verify_queues.sh` - OVS linux-htb QoS with 2 queues, measured with
    iperf3 (after fixing a port-direction mistake - see
    docs/troubleshooting.md): default queue ~9.6 Mbit/s vs low queue
    ~1.9 Mbit/s
- Wrote docs/installation-guide.md, docs/troubleshooting.md,
  docs/integration-contract.md, docs/environment-report.md,
  config/environment.example.env.
- Found and fixed a real bug in the queue test's own cleanup code
  (`ovs-vsctl destroy qos -- --all` has `--all` in the wrong position,
  so it silently did nothing). Caught by manually checking
  `ovs-vsctl list qos`/`list queue` after a run instead of trusting the
  script's "cleanup complete" message - confirmed clean after the fix.

### Tested
See docs/environment-report.md for the full component-by-component
table with real test results.

### Open issues
- The OVS queue measurement used TCP iperf3, which reacted with bursty
  /zero-throughput intervals under the sudden rate cut (expected TCP
  behaviour, not a tool fault). Real priority-queue tests in later
  phases should use UDP iperf3, matching the real video flow.
- `docs/requirements/*.pptx` have not been read yet - that is the first
  step of the next phase.
- RAM is modest (5.8 GiB) for running Mininet + Ryu + Flask + Vite +
  a browser all at once; watch for slowdowns under the full stack.

### Exact commands (also in docs/installation-guide.md)
```
bash scripts/inspect_environment.sh
bash scripts/install_lab_dependencies.sh
bash scripts/verify_environment.sh
bash scripts/test_mininet.sh
bash scripts/verify_controller.sh
bash scripts/verify_queues.sh
bash scripts/cleanup_lab.sh   # after any test run
```

## Phase 1: Topology and controller basics - DONE (2026-10-25)

### Done
- Read both review decks with python-pptx; wrote docs/requirements-summary.md
  (problem, objectives, architecture, tools, test plan, expected results,
  and the known differences to document later). Review 2 slide 7
  ("System Architecture") has only drawn shapes, no text.
- config/config.yaml: video port 5004, poll interval 2 s, threshold 0.80,
  3 consecutive polls, cooldown 20 s, max 4 reroutes per run, capacity
  10 Mbit/s per link, queue min rates (video 6, default 4), background
  light 3 / heavy 9 Mbit/s, fixed topology with port numbers.
- sdn/qos_config.py: shared loader + validation (system python3 + PyYAML
  5.4, and venv + PyYAML 6.0).
- sdn/topology.py: h1, h3 on s1; h2 on s4; Path A s1-s2-s4, Path B
  s1-s3-s4; OpenFlow 1.3, fail-mode secure, remote controller
  127.0.0.1:6653; OVS linux-htb QoS (max-rate = capacity, queue 0
  default, queue 1 video) on both ends of every switch link; no TCLink.
  Only removes QoS rows it created (tagged external_ids:owner=sdn-qos).
- sdn/controller.py: switch connect (table-miss DROP, ARP to controller,
  port description request), LLDP link discovery checked against config,
  proxy ARP from the config host table (no flooding anywhere), default
  rules per destination IP along Path A (s3 gets Path B rules so it is
  consistent), video rules (UDP port 5004 plus the h1<->h2 ICMP probe) on
  Path A, installed from the far end backwards. Events in JSON lines.
- sdn/labutil.py, sdn/verify_phase1.py, scripts/verify_phase1.sh.
- Bug found and fixed in the first real run: `mn -c` kills ryu-manager
  (see docs/troubleshooting.md). Cleanup now runs before Ryu starts.

### Tested (real run, results/verify/phase1-20261025-201535.log, 11/11 PASS)
- Ryu listens on 127.0.0.1:6653 only (`ss -ltnp`).
- 8 OVS QoS ports; `tc class show dev s4-eth2`: root 10Mbit, class 1:1
  rate 4Mbit ceil 10Mbit prio 1 (default), class 1:2 rate 6Mbit ceil
  10Mbit prio 0 (video).
- Port mapping exactly as configured; all 8 directed links discovered by
  LLDP with matches_config=true; all 4 switches is_connected: true.
- No rule with FLOOD/ALL actions. Idle 10 s: about 22-24 LLDP packets
  per switch, 27 other packets in total across all 4 switches (dropped
  by table-miss), i.e. no storm.
- ping h1->h2 0% loss, RTT avg 0.107 ms; pingall 0% dropped.
- iperf3 TCP h1->h2: 9.57 Mbit/s (link capacity 10, so the OVS HTB
  limit is active on the path).
- iperf3 UDP video h2->h1 on port 5004 at 4 Mbit/s: 4.00 Mbit/s, jitter
  0.092 ms, loss 0/1741.
- Video rule counters: s1 +1715, s2 +1715, s4 +1715, s3 +0, so the
  video used Path A only.
- Proxy ARP answered all 6 host pairs; ARP rule on s2/s3 saw 0 packets
  (no ARP leaks into the core).

### Open issues
- The ~27 idle non-LLDP packets dropped by table-miss are not
  identified yet (likely leftover host noise); harmless, but can be
  checked by dumping one switch's drops in a later phase.
- Two root-owned `iperf3 -s -D` daemons from Phase 0 are still running
  in the root namespace. They do not affect Mininet hosts. Remove with
  `sudo pkill -x iperf3` if wanted.

### Exact commands
```
bash scripts/verify_phase1.sh          # full Phase 1 check, as normal user
# interactive use:
.venv/bin/ryu-manager --ofp-listen-host 127.0.0.1 --ofp-tcp-listen-port 6653 \
    --observe-links sdn/controller.py    # terminal 1
sudo python3 sdn/topology.py           # terminal 2 (Mininet CLI)
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
```
Order matters: run `bash scripts/cleanup_lab.sh` BEFORE starting Ryu,
never after (mn -c kills ryu-manager).

## Phase 2: Monitoring and congestion detection - DONE (2026-10-25)

### Done
- sdn/monitor.py (no Ryu dependency): RateTracker (rates from cumulative
  counters, using the switch's own counter clock, skips counter resets)
  and CongestionDetector (N consecutive polls over threshold to detect,
  N under to clear, missing samples change nothing).
- sdn/tests/test_monitor.py: 10 unit tests.
- Controller: polling thread every poll_interval_s sends port stats and
  video-rule flow stats requests; per directed link (e.g. s4->s2 = tx of
  s4's port to s2) computes Mbit/s, utilization, tx drops/s; video rate
  per switch from the video rule byte counter (classification by port);
  events congestion_detected / congestion_cleared / stats_missing;
  one metrics record per poll in metrics.jsonl (stale=true if a switch
  did not answer). No reroute yet.
- scripts/lab_common.sh (shared start/stop helpers, cleanup before Ryu),
  sdn/verify_phase2.py + scripts/verify_phase2.sh (62 s traffic run:
  video only, light, heavy, video only, plus ping from h1).

### Tested
- 10/10 unit tests: `.venv/bin/python -m unittest discover -s sdn/tests -v`
- Real run, results/verify/phase2-20261025-202455.log, 12/12 PASS:
  - s4->s2 utilization: video only 41%, light 72% (no congestion),
    heavy 100%, after 41%. s4->s3 and s3->s1 stayed 0%.
  - congestion_detected on s4->s2 and s2->s1 at t=35.4 s, 5.4 s after
    heavy load started (3 polls of 2 s); congestion_cleared at t=55.4 s.
  - Video rule rate at s4: 4.12 Mbit/s; s3 video rate 0 the whole run.
  - No stats_missing events, no Ryu errors, 32 metrics records.
  - Host side (ping/iperf3, not the controller): ping RTT avg 0.19 ms in
    light vs 90.73 ms in heavy; video jitter 0.107 ms vs 0.606 ms; video
    loss 0% in every window.

### Finding: congestion showed up as delay, not loss (Mininet artifact)
- Heavy background was asked for 9 Mbit/s but only sent 5.76 Mbit/s,
  with 0 loss. Nothing was dropped at the bottleneck queue.
- Cause: all Mininet hosts share one kernel. A packet waiting in s4's
  HTB queue still counts against the sending socket's buffer on h2, so
  when ~110 KB are queued (default UDP send buffer) iperf3 just blocks.
  110 KB at 10 Mbit/s is about 90 ms, which matches the ping RTT. The
  queue itself (1000 packets, from the veth txqueuelen) never fills.
- In a real network the server and router are separate machines and the
  router would drop. Planned fix (start of Phase 3): give the HTB queues
  a realistic, configurable buffer (for example 50 packets, about 60 ms
  at 10 Mbit/s) by setting txqueuelen on the switch ports before OVS
  creates the queues, then re-measure so loss is visible.
- Monitoring and detection are unaffected: they read port counters.

### Exact commands
```
.venv/bin/python -m unittest discover -s sdn/tests -v
bash scripts/verify_phase2.sh          # about 2 minutes, normal user
```

## Phase 3: Rerouting and priority queues - DONE (2026-10-25)

### Done
- Buffer fix for the Phase 2 finding: config links.queue_limit_packets
  (50). topology.apply_qos sets txqueuelen on each switch port before OVS
  creates the HTB queues, so each queue's FIFO holds 50 packets.
- Controller, qos mode:
  - set_queue to the video queue (1) on every switch-to-switch hop for the
    video rules and the ping probe; other traffic stays in queue 0.
  - level-triggered reroute check once per poll: if a link on the video
    path is congested, pick the other path with the lowest fresh load;
    move only if (its load + video rate / capacity) < threshold, not in
    cooldown, previous reroute confirmed, and under max_reroutes_per_run.
    Every refusal is logged once as reroute_skipped with the reason.
  - make-before-break: new generation of video rules (priority 20+gen,
    cookie 0x20+gen), barrier, delete old generation by exact cookie,
    barrier; reroute_confirmed logs the install time.
  - queue stats polling (OFPQueueStatsRequest) -> per-queue Mbit/s in
    metrics.jsonl.
  - SDN_QOS_REROUTE=0 / SDN_QOS_QUEUES=0 switch one mechanism off.
  - No automatic move back to Path A (simpler, cannot flap).
- labutil: run_traffic (video + background schedule + timed snapshots),
  per-window ping (with -O, so losses are counted) and iperf3 parsing,
  tc class counters and leaf limits.
- sdn/verify_phase3.py (one scenario), sdn/compare_phase3.py,
  scripts/verify_phase3.sh (baseline, queue_only, qos back to back).

### Tested (without sudo)
- Controller compiles; offline run with fake switches: congestion on A
  -> reroute to B (predicted 40%), message order on s4/s3: adds (cookie
  0x21, prio 21), barrier, delete cookie 0x20, barrier; s2 gets only the
  delete; set_queue(1) before output on gen-0 rules; when B then
  congested: reroute_skipped reason=cooldown. Code path test only.
- New parsers re-run on the Phase 2 files reproduce the Phase 2 numbers.

### First real run (results/verify/phase3-20261025-203458.log)
Mechanisms worked; measurements had two problems, both fixed since:
- Reroute: congestion detected 7.1 s after background start, one reroute
  A -> B at +9.1 s, barrier confirmed in 14.8 ms; dump-flows before: video
  rule on s2 not s3, after: on s3 with set_queue:1, none on s2; video
  rate s3 4.05 / s2 0.00 Mbit/s; s4->s3 at 41%; queue 1 on s4-eth3
  4.12 Mbit/s.
- Queue only: video in queue 1 on s4-eth2 at 4.12 Mbit/s, queue 1 had 0
  kernel drops; video received 4.00 Mbit/s, ping avg 0.12 ms vs baseline
  2.77 Mbit/s and 60.31 ms (ping lost 61 in baseline, 0 with queue).
- Problem 1: iperf3 -R loss counters were corrupt (see
  docs/troubleshooting.md). Fixed: normal direction, receiver = server.
- Problem 2: single-flow sender still throttled by the shared kernel
  (background 5.73 of 9 Mbit/s, 0 drops). Fixed: queue limit 25 packets
  plus a "sender not slowed down" check.
- Problem 3: leaf-limit check used `tc qdisc show` without `invisible`.
- Also: reroute decision now runs immediately when congestion is
  detected on the video path (it waited for the next poll, about 2 s).
These first-run numbers are from a flawed measurement setup and are not
used as results.

### Second real run (results/verify/phase3-20261025-204354.log)
- Measurement setup now valid: buffer 25 packets on both queues, every
  sender sent exactly what it was asked (video 4.00, background 9.00).
- baseline 8/8, queue_only 8/8 PASS. qos 6/11: no reroute, because of a
  video-rate bug (two rules shared one tracker entry, see
  docs/troubleshooting.md). Fixed and tested offline.
- Valid numbers from this run (one run each, host-side, 20-50 s window):
  baseline video loss 16.97%, 3.32 Mbit/s, jitter 0.659 ms, ping 30.40 ms;
  queue_only video loss 0.00%, 4.00 Mbit/s, jitter 0.075 ms, ping 0.11 ms.
  Kernel: queue 1 (video) 0 drops; queue 0 about 11100 drops in each run.

### Pre-run review before the third run (no sudo needed)
- Full offline simulation (scratchpad sim_qos.py) of the real controller
  with fake switches that keep a real rule table (adds, deletes by cookie,
  barriers) and route the video by whichever installed rule wins:
  qos mode -> one reroute A->B, predicted 0.40, s3 4.0 / s2 0.0 Mbit/s,
  no video rules left on s2, s3 rules carry set_queue, barrier confirmed;
  both reply orders tested. queue_only and baseline -> no reroute.
- Fixed found in review: reroute decision now runs after the whole stats
  reply is stored (was mid-reply); reroute_pending set before barriers
  are sent; reroute_unconfirmed timeout so a lost barrier cannot block
  rerouting forever; trigger-link check accepts either Path A video link
  (which one fires first depends on reply order).
- Unit tests pass, all scripts compile, Ryu starts cleanly, analysis code
  replayed on the saved second-run data without errors.

### Third real run: ALL PASS (results/verify/phase3-20261025-205348.log)
baseline 8/8, queue_only 8/8, qos 13/13. Every sender sent exactly what
it was asked (video 4.00, background 9.00 Mbit/s), queue limit 25 on
both HTB classes.

Proof of rerouting (qos scenario):
- congestion_detected 7.2 s after background start; reroute A -> B at
  +7.2 s (trigger s2->s1, same stats reply); barrier confirmed 9.5 ms;
  no reroute_skipped, exactly one reroute.
- dump-flows before: video rule on s2, none on s3; after: on s3 with
  set_queue:1, none on s2 (results/verify/phase3-20261025-205348/qos/
  flows_before.txt and flows_end_heavy.txt).
- video rule rate s3 4.12 / s2 0.00 Mbit/s; port counters s4->s3 41%;
  Path A s4->s2 93% after the reroute (background alone).
Proof of the priority queue:
- OVS queue stats: video in queue 1 at 4.12 Mbit/s on s4-eth2
  (queue_only) and on s4-eth3 (qos). Kernel tc: queue 1 dropped 0 in all
  runs; queue 0 dropped 11144 (baseline), 11081 (queue_only), 1997 (qos).

Host-side results, 20-50 s window (ONE run per scenario, indicative):
| metric | baseline | queue_only | qos |
|---|---|---|---|
| video Mbit/s | 2.15 | 4.00 | 4.00 |
| video loss % | 46.20 | 0.00 | 0.00 |
| video jitter ms | 0.528 | 0.066 | 0.064 |
| ping avg ms | 29.76 | 0.11 | 0.07 |
| ping lost | 56 | 0 | 0 |
| background Mbit/s | 7.55 | 5.70 | 9.00 |
| background loss % | 16.1 | 36.6 | 0.0 |

Observations to report honestly:
- Baseline video loss varied a lot between runs with the same settings
  (16.97% in run 2, 46.20% in run 3): a shared FIFO splits the loss
  between flows unpredictably. This is why Phase 4 does 3 runs per case.
- queue_only protects the video by taking bandwidth from the background
  (background loss 36.6%). Rerouting also frees Path A, so with qos the
  background got its full 9 Mbit/s with 0 loss after the reroute.
- Before the reroute (10-17 s in qos) the queue already protected the
  video (0% loss in heavy_early).
- No automatic move back to Path A after congestion clears (design
  choice: simpler, cannot flap).

### Exact commands
```
bash scripts/verify_phase3.sh                      # about 5 minutes
python3 sdn/compare_phase3.py results/verify/phase3-<time>   # table again
```

## Phase 4: Backend API and experiment runner - DONE (2026-10-25)

### Done
- backend/app.py (Flask, 127.0.0.1:5000, refuses other bind addresses):
  POST /api/ingest; GET /api/health, status, metrics, events, flows,
  topology, queues, settings, experiments, experiments/<id|latest>,
  environment. In-memory ring buffers plus results/live/*.jsonl.
  controller.reachable=false when nothing arrived for 3 polls + 2 s; no
  fallback data. Optional token (SDN_QOS_API_TOKEN), CORS allowlist
  (SDN_QOS_CORS_ORIGINS), both readable from config/environment.env
  (gitignored; documented in config/environment.example.env).
- Controller pushes metrics, events and a heartbeat per poll to Flask from
  a separate green thread with a 500-record outbox; logs reachability
  changes once.
- sdn/playout_model.py: playout buffer MODEL (startup 2 s, resume 1 s)
  fed by per-second received video bits; stall count, stall time,
  startup delay.
- sdn/run_analysis.py: per-run numbers (validity, host side per window,
  model, controller, kernel tc drops); re-runnable on saved data.
- sdn/run_experiment.py: --mode, --load, --duration, --runs; per run:
  mn -c, Ryu started directly as the normal user (Popen user/group), same
  topology/QoS/traffic, snapshots, cleanup; interleaved order; meta.json
  (versions), config.yaml copy, runs.csv, summary.json/csv, per-run raw
  files and analysis.json. Invalid runs (sender throttled, setup failure)
  excluded from the summary and listed.
- sdn/print_summary.py, scripts/run_experiments.sh.

### Tested (without sudo)
- 15 sdn unit tests (monitor + playout model), 11 backend tests (no data
  -> unreachable, stale detection, bad ingest, token, CORS allowlist,
  experiment ids, environment counts).
- Real ryu-manager (no switches) pushing to a real Flask: heartbeat and
  events arrive, status reachable=true but live=false (no metrics);
  stopping Flask -> one "not reachable" warning.
- run_analysis replayed on the Phase 3 runs reproduces Phase 3 numbers.
- run_experiment.main() dry run with the network part faked (copies of
  real Phase 3 data): plan order, partial results, invalid-run handling,
  meta/runs/summary files, print_summary table.
- start_ryu/stop_ryu as the normal user: listens on 127.0.0.1:6653,
  stops cleanly. Backend binds 127.0.0.1:5000.

- Per-run watchdog (SIGALRM, duration + 120 s, covers everything from
  mn -c to the end of traffic): a stuck run is marked failed
  ("WatchdogTimeout"), cleaned up, and the next run starts. Tested
  offline with a hanging network build and a hanging mn -c: aborted on
  time, cleanup ran, the following run worked. Progress line every 15 s
  of traffic. Ctrl+C still cleans up and writes the summary of the runs
  finished so far.

### Real experiment: results/experiments/20261025-211618 (log: results/experiments/run-20261025-211618.log)
12/12 runs valid (every sender sent its full rate), 0 watchdog aborts,
0 controller errors, 0 stats_missing, 0 reroute_skipped. Took 16 min
(about 80 s per run). In all 3 qos-heavy runs the end-of-load
dump-flows shows the video rules on s3 with set_queue:1; no reroute in
any light run.

Steady window 20-50 s, mean (min-max) over 3 runs. Host = ping/iperf3,
model = playout buffer MODEL, controller = OpenFlow stats, tc = kernel.
| metric | light baseline | light qos | heavy baseline | heavy qos |
|---|---|---|---|---|
| video received Mbit/s (host) | 4 | 4 | 2.55 (2.2-3.24) | 4 |
| video loss % (host) | 0 | 0 | 36.2 (19-45) | 0 |
| video jitter ms (host) | 0.076 | 0.071 | 0.566 (0.488-0.698) | 0.074 |
| ping RTT avg ms (host) | 0.168 | 0.111 | 31.4 (30.7-31.8) | 0.115 |
| ping probes lost (host) | 0 | 0 | 58 (57-59) | 0 |
| background Mbit/s (host) | 3 | 3 | 7.16 (6.47-7.51) | 9 |
| background loss % (host) | 0 | 0 | 20.5 (16.6-28.1) | 0 |
| buffering events (model) | 0 | 0 | 6.33 (3-8) | 0 |
| buffering time s (model) | 0 | 0 | 7.1 (3.31-9.07) | 0 |
| congestion detected after s (ctl) | - | - | 5.82 | 6.03 |
| reroute after s / install ms (ctl) | - | - | - | 6.04 / 11.1 |
| util s4->s2 Path A (ctl) | 0.721 | 0.721 | 0.999 | 0.926 |
| util s4->s3 Path B (ctl) | 0 | 0 | 0 | 0.412 |
| drops queue 0 s4-eth2 (tc) | 0 | 0 | about 11200 | about 1660 |
| drops queue 1 s4-eth2 (tc) | 0 | 0 | 0 | 0 |

How to read it honestly:
- Light load: no congestion, so QoS changes nothing that matters (loss 0
  in both; ping differences are below 0.1 ms on average, within VM noise).
  It also shows there were no false reroutes at 72% utilization.
- Heavy load: QoS removed video loss, jitter and buffering (model) and
  kept ping below 1 ms; the background also did better (9 vs 7.16
  Mbit/s) because rerouting split the two flows over both paths.
- Baseline heavy loss varies a lot between runs (19% to 45%): video and
  background share one FIFO queue and the split of drops is not stable.
- The ~1660 queue-0 drops in qos heavy happen in the ~6 s before the
  reroute (background only; video was protected in queue 1).
- Limits: 3 runs per case, one VM, Mininet emulation, iperf3 UDP instead
  of a real video stream, buffering from a model, video never moves back.

### Open issues
- Flask was not running during this experiment, so "metrics reach Flask
  during a real run" is not yet proven; Phase 6 covers it.
- results/ is gitignored; the final experiment summary needs to be
  copied somewhere tracked for the dashboard/report (Phase 5/7).

### Exact commands
```
bash scripts/run_experiments.sh                 # about 16-19 minutes
python3 sdn/print_summary.py                    # table of the latest experiment
python3 sdn/run_analysis.py results/experiments/<id>/<run>   # re-analyse one run
.venv/bin/python backend/app.py                 # API on 127.0.0.1:5000
.venv/bin/python -m unittest discover -s sdn/tests
.venv/bin/python -m unittest discover -s backend/tests
```

## Phase 5: Frontend dashboard - DONE (2026-10-25)

### What was built
- frontend/: React 19 + Vite 8 + Tailwind 4 + Recharts 3 + lucide-react,
  written by hand (no interactive create-vite). HashRouter, so it works on
  any static host without rewrite rules.
- Five pages: Overview, Topology, QoS monitoring, Experiments, Event logs.
- LIVE LAB / DEMO MODE switch plus a permanent banner at the top:
  - LIVE: only talks to Flask (VITE_API_BASE_URL, default
    http://127.0.0.1:5000), optional Bearer token entered in the
    Connection panel (stored in the browser only, never in the build).
    Any failure clears the data and shows a red error state. The banner
    separates "backend not reachable" from "controller not sending".
  - DEMO: everything from frontend/src/demo/demoData.js (invented,
    deterministic, every object demo: true), "DEMO DATA" stamp on every
    page, card and chart. Starts 20 polls into a scenario (congestion on
    Path A, video already on Path B) and adds a poll every 2 s.
- Every card says its source: controller, end hosts, playout model, tc,
  config or verify logs. Delay, jitter and loss are never shown as
  controller data: live charts show controller rates only, host metrics
  come from recorded runs.
- Charts: colour-blind safe palette (validated), one y-axis each, legend,
  hover tooltip, and a Table toggle on every chart.

### Backend changes
- New sdn/run_timeseries.py and endpoint
  GET /api/experiments/<id>/runs/<run>/timeseries: per-second host data
  (video rate, loss, jitter, ping, background, buffer model level) plus
  controller polls and events of one recorded run.
- /api/experiments/<id> now lists run_dirs.
- /api/status, /api/flows, /api/topology, /api/queues only return live
  fields (video path, link loads, queue rates) while the controller is
  reachable, so stale numbers are never served as current.
- config/config.yaml: fixed an outdated comment (iperf3 -R no longer used).

### Tested
- npm run build: OK (one 727 kB bundle, size warning only).
- Backend unit tests: 12/12 OK (new: timeseries, stale data hidden).
- Screenshots of all five pages in DEMO mode (headless Firefox); fixed
  topology label overlap, chart label collisions, zero-value bar labels.
- LIVE mode with Flask up and no controller: banner shows "controller not
  sending data". LIVE pages with data were not seen in a screenshot
  (headless Firefox captures before the fetch returns); user is checking
  LIVE mode in the browser.

### Open issues
- LIVE mode with a running controller is tested in Phase 6.
- Host metrics (delay, jitter, loss) are not streamed live, only from
  recorded runs. This is a deliberate scope choice.

### Exact commands
```
cd frontend && npm install          # once
cd frontend && npm run dev          # http://127.0.0.1:5173
cd frontend && npm run build && npm run preview   # http://127.0.0.1:4173
http://127.0.0.1:4173/?mode=demo    # open directly in DEMO MODE
```

## Phase 6: Full chain and lab scripts - DONE (2026-10-25)

### What was built
- scripts/start_lab.sh [qos|baseline] [--auto]: starts (or reuses) Flask
  on 127.0.0.1:5000 and the dashboard on 127.0.0.1:5173, then runs
  sudo python3 sdn/lab.py. sudo is asked once.
- sdn/lab.py: mn -c, Ryu as the normal user (same start_ryu as the
  experiment runner), network plus OVS queues, waits for switches and
  rules, then a menu: v video, l/h/o background light/heavy/off,
  a 60 s auto scenario, s status, m restart in the other mode, c Mininet
  CLI, q quit. Saves results/lab/<id>/ (ryu.log, metrics.jsonl,
  events.jsonl, host.jsonl, lab.log).
- Live end-host measurements: sdn/host_monitor.py parses iperf3 server
  lines (-i 1 --forceflush) and ping -D -O; sdn/lab_traffic.py sends one
  sample per second to Flask (kind host). The controller still never
  reports delay, jitter or loss.
- Backend: kind "host" in /api/ingest, GET /api/host. Host samples do not
  count as controller activity.
- Dashboard: "Live: end-host measurements" on QoS monitoring, an
  end-host card on Overview; live charts show only the latest run_id.
- scripts/stop_lab.sh: stops the lab (SIGTERM, clean shutdown), the
  Flask and dashboard processes that start_lab.sh started (pid files),
  leftover Ryu, and runs scripts/cleanup_lab.sh only if Mininet
  interfaces are left after a crash.

### Tested offline (no sudo)
- sdn tests 20/20 (new: parser on real iperf3 3.9 output, and a real
  iperf3 + ping + HTTP test on localhost), backend 13/13.
- Menu logic with a fake network and real localhost traffic: video,
  light/heavy/off, status, mode switch (down then up), quit. Samples
  reached the real Flask.
- start_lab.sh / stop_lab.sh with a fake sudo: reuse of running servers,
  fresh Flask start, pid-file stop of only our own processes.

### Tested for real (user ran start_lab.sh qos --auto, then baseline --auto)
Chain: Ryu -> Flask -> dashboard, plus hosts -> Flask -> dashboard.
- Everything Ryu wrote also reached Flask: qos run 111/111 metrics,
  30 events; baseline 53/53 metrics, 22 events. Host samples 219/219 and
  105/105. Flask answered 3070 requests, no 4xx/5xx; the dashboard polled
  /api/status, /api/metrics and /api/host throughout. ryu.log: no errors.
- QoS run (lab-20261025-222442-qos), heavy background 39 s:
  congestion detected and reroute to Path B 6.8 s after the load
  started, rules confirmed in 7.7 ms. Hosts during load (10 to 40 s):
  video 4.0 Mbit/s, 0% loss, jitter 0.078 ms, ping 0.105 ms, background
  9.0 Mbit/s with 0% loss.
- Baseline run (lab-20261025-223007-baseline): congestion detected at
  6.0 s, no reroute (as designed). Hosts during load: video 2.22 Mbit/s,
  44.5% loss, jitter 0.648 ms, ping 31.8 ms, 62 pings lost, background
  7.47 Mbit/s with 17% loss.
- These single live runs agree with the Phase 4 experiment (3 runs per
  case); the experiment remains the result to report.
- Clean shutdown with q: Ryu, traffic, network and QoS rows removed, and
  the next start worked.

### Open issues
- Two stale root "iperf3 -s -D" daemons from Phase 0 (harmless, root
  namespace only; remove with: sudo pkill -f 'iperf3 -s -D').

### Exact commands
```
bash scripts/start_lab.sh              # QoS mode, then use the menu
bash scripts/start_lab.sh baseline     # best-effort baseline
bash scripts/start_lab.sh qos --auto   # run the 60 s scenario at once
bash scripts/stop_lab.sh               # stop everything (also after a crash)
.venv/bin/python -m unittest discover -s sdn/tests
.venv/bin/python -m unittest discover -s backend/tests
```

## Phase 7: Production build and deployment - DONE (2026-10-25, deploy itself is manual)

### What was done
- frontend/.env.production: VITE_DEFAULT_MODE=demo,
  VITE_API_BASE_URL=http://127.0.0.1:5000. frontend/.env.example for
  local overrides. No token or secret is ever built into the site.
- frontend/vercel.json: Vite, npm ci, npm run build, output dist, and
  security headers (CSP allowing only own scripts and connections to
  HTTPS or localhost, no framing, nosniff, no referrer).
- Backend hardening for the optional tunnel: requests carrying proxy
  headers (Forwarded, X-Forwarded-For, X-Real-IP, CF-Connecting-IP) are
  refused unless SDN_QOS_API_TOKEN is set; /api/ingest only accepts
  direct requests from 127.0.0.1/::1.
- Frontend unit tests (vitest): every demo response and row is marked
  demo: true, the scenario and config field names, helpers.
- docs/deployment.md: settings, local production test, exact GitHub and
  Vercel steps, and how live mode could be reached safely (token, CORS
  allowlist, HTTPS tunnel to port 5000 only; never 6653/8080/SSH).

### Tested
- npm run build OK (731 kB JS, 217 kB gzipped); npm test 18/18.
- Backend tests 14/14 (new: tunnelled requests and remote ingest).
- dist served locally with the exact vercel.json headers: opens in DEMO
  MODE with no URL parameter, all pages render under the CSP, phone width
  (390 px) has no page-wide horizontal scroll.
- git add dry run: 85 files, no .venv, node_modules, dist, results or
  config/environment.env; no secrets found.

### Deployed (by the user, 2026-10-25)
- GitHub: https://github.com/reydar-05/sdn-qos (branch main)
- Vercel: https://sdn-qos.vercel.app (Root Directory frontend)
- Checked from the VM: HTTP 200, CSP / X-Frame-Options / nosniff /
  Referrer-Policy headers present, same bundle as the local build, page
  renders in DEMO MODE with the banner and DEMO DATA stamps.
- Fixed after deploy: the Experiments intro said "read from the result
  files" in DEMO MODE too; it now says the demo numbers are invented.
  Goes live with the next git push. (Pushed: commit acb7184; the main
  URL serves the same bundle as the local build.)
- LIVE LAB on the Vercel site from a browser on the VM: created
  config/environment.env (gitignored) adding https://sdn-qos.vercel.app to
  SDN_QOS_CORS_ORIGINS. Checked with curl: that origin gets the CORS
  header (also on the preflight), other origins do not; Flask still on
  127.0.0.1 only. Browser check pending (user). docs/deployment.md
  section 4.
- Per-deployment URLs (sdn-<hash>-renu-gopu.vercel.app) redirect to a
  Vercel login: Vercel deployment protection, expected. Share only
  https://sdn-qos.vercel.app.
- The tunnel was explained, not installed or tested.

## Phase 8: Documentation - DONE (2026-10-25)

Done:
- README.md: description, Mermaid architecture diagram, measured results
  table (heavy load) with how to read them, quick start, lab menu,
  dashboard modes, layout, security.
- docs/how-it-works.md: network, loop safety, queues, video
  identification, monitoring, detection, anti-flap, make-before-break,
  measurement sources, playout model and why iperf3, experiment design,
  results, live lab, limitations.
- docs/mapping-to-reviews.md: every objective, research gap, step, tool,
  test case and expected result from both decks, marked Met / Partly met /
  Different with evidence. Research gap 1 (fast polling) is Partly met:
  the experiments polled every 2 s.
- docs/demo-script.md: timed 5 minute faculty demo with lines to say,
  preparation steps and a troubleshooting table.
- docs/viva.md: likely questions with short answers.
- docs/results/20261025-211618/: copy of the final experiment (summary,
  runs, config, per-second data of one run per mode) so the results are in
  git.

Tested:
- Every number quoted in the docs was checked against
  docs/results/20261025-211618/summary.txt and summary.json; controller
  function and event names cited were checked in sdn/controller.py.
- No em or en dashes in README.md, docs/*.md or the frontend sources.

Open issues:
- The new docs are not pushed yet (git add, commit, push).
- LIVE LAB on https://sdn-qos.vercel.app from the VM browser: CORS checked
  with curl, browser check still to do.
- Mermaid diagram not rendered locally; check it on GitHub after pushing.



