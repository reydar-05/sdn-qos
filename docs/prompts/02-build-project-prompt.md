# BUILD PROMPT: The project (paste into Claude Code after Phase 0 is verified)

Read CLAUDE.md, docs/PROGRESS.md and docs/environment-report.md first. Reuse the existing scripts, venv and installed packages. Do not reinstall or recreate what already works. If Phase 0 left anything unverified (especially Ryu or OVS queues), fix that before building on top of it.

Read the two review decks in docs/requirements/ (use python-pptx) and treat them as the requirements. At the start, write docs/requirements-summary.md listing what the decks promise (problem, objectives, architecture, tools, test plan, expected results) so we can check against it at the end.

You are my senior SDN engineer and teacher. I am a CSE student, so keep it moderately complex, explain each major step in plain words, and make it demonstrable on my own VM. I do not want only a website or sample code: I want a working SDN network, real measurements, a dashboard, and deployment of the frontend.

## Work in phases. At the end of each phase: run the tests, update docs/PROGRESS.md, summarise in a few lines, and STOP. I will say "continue".

### Phase 1: Topology and controller basics
- config/config.yaml: video port (default 5004), poll interval, utilization threshold, consecutive polls needed, cooldown seconds, bottleneck capacity per link, background traffic rate.
- sdn/topology.py (runs with sudo and the system python3): h1 client and h3 background host on s1, h2 server on s4, Path A s1-s2-s4, Path B s1-s3-s4, OpenFlow 1.3, remote controller 127.0.0.1:6653. Bottleneck and queues are done with OVS QoS, not TCLink.
- sdn/controller.py (Ryu): handle switch connect, learn port mappings, handle ARP without flooding, install baseline per-flow forwarding on Path A for video and background, and verify end to end ping and iperf3 h1 to h2.
- Verify and show output: switches connected, port mapping, no broadcast storm, flows installed (`ovs-ofctl -O OpenFlow13 dump-flows`).

### Phase 2: Monitoring and congestion detection
- Poll port stats every N seconds, compute throughput and utilization per link from byte deltas and configured capacity. Handle missing or late stats (log, skip, keep last state).
- Classify video traffic by the configured port.
- Congestion detection: utilization above threshold for N consecutive polls. Log every event as JSON lines in results/.
- Reproduce congestion with background iperf3 and show utilization rising in real data.

### Phase 3: Rerouting and priority queues
- On congestion, compute the alternative path (the less utilized of the available paths), install the new flow rules with higher priority, remove or let the old ones expire, and log the action. Add cooldown and hysteresis so it never reroutes endlessly.
- Configure OVS linux-htb queues (video queue with guaranteed rate, default queue for the rest) and send video through the queue with the set-queue action.
- Verify and show proof: the flows moved (dump-flows before and after, port counters on the new path), and the queue is applied (ovs-vsctl list qos/queue, and a measurement showing the video share). Do not claim priority until measured.

### Phase 4: Backend API and experiment runner
- backend/ (Flask, bound to 127.0.0.1): POST /ingest for Ryu metrics and events, and GET endpoints for status, metrics time series, flows and paths, queue status, events, settings, experiment list and results. Store data as JSON/CSV under results/. Optional simple token auth through an env var.
- sdn/run_experiment.py (sudo, system python3) with --mode baseline|qos --load light|heavy --duration 60 --runs 3:
  - Baseline: same topology and traffic, controller does static forwarding only, no reroute, no queues.
  - QoS: reroute and queues enabled.
  - Same traffic rates, capacities and durations in both. Video is iperf3 UDP on the video port. Background is iperf3 on the same bottleneck. Run ping from h1 to h2 during the test.
  - Collect: throughput and utilization (controller stats), delay (ping avg and max), jitter and loss (iperf3 UDP server report), reroute time if it happened. Buffering ONLY if an instrumented client measures it, and then label it clearly as a playout buffer model.
  - Save raw results and a summary to results/ as CSV and JSON with timestamps and the config used. Always clean up Mininet at the end.
- Run the experiments for real and save the results. Never invent numbers. Describe the limitations honestly (VM variance, small number of runs, simulated links).

### Phase 5: Frontend dashboard
React + Vite + JavaScript + Tailwind CSS + lucide-react + Recharts, responsive and professional. Five pages:
1. Overview: controller status, active flows, throughput, link utilization, congestion state.
2. Topology: switches, hosts, both paths, capacities, active path, congestion highlight.
3. QoS monitoring and traffic management: time series (throughput, utilization, delay, jitter, loss where available), flow classification, current path and queue status.
4. Experiments and results: environment checks, baseline versus QoS comparison charts and a table from the real results files, plus the limitations.
5. Event logs: congestion events, route changes, controller errors.
Thresholds, interval, capacity and video port live in config/config.yaml and are shown read-only on the Overview page.

Two modes with a clear switch and a permanent banner showing the current mode:
- LIVE LAB: real data from Flask. If Flask or Ryu is unreachable, show an explicit error state. Never silently switch to demo data.
- DEMO MODE: repeatable sample data from one clearly named file, with "DEMO DATA" visible on every chart and page. Works with no backend.

### Phase 6: Connect and test the whole chain
Run the real chain in this order and show proof of each: start Ryu, start Mininet, switches connected, topology and ports known, client to server connectivity, baseline flows, background traffic, congestion detected, alternate-path rules installed, queue configured and verified, metrics sent to Flask, data visible in the dashboard in LIVE mode. Write scripts/start_lab.sh and scripts/stop_lab.sh with the exact order and cleanup. Fix real errors, do not skip steps.

### Phase 7: Production build and deployment
- Frontend env var VITE_API_BASE_URL and VITE_DEFAULT_MODE. Add the Vercel config. Run `npm run build` and test the production build locally before claiming ready.
- The Vercel deployment must work fully in DEMO MODE with no backend. Document the variables.
- Explain how live mode could connect to the VM: Vercel is HTTPS so the backend needs an HTTPS URL, for example through a tunnel, with token auth and a CORS allowlist. Never expose the OpenFlow port or any controller interface. If you cannot deploy from here, give me exact step by step instructions (GitHub plus Vercel).

### Phase 8: Documentation, demo and viva
- README.md: install commands, architecture diagram (text or Mermaid), dependencies, startup order, experiment procedure, troubleshooting, deployment.
- docs/how-it-works.md in simple words: how Mininet, Open vSwitch and Ryu work together, how OpenFlow rules are installed, how congestion is reproduced, how the alternative path is chosen, how the priority queue is configured, how to prove rerouting happened, how to read the result graphs.
- docs/mapping-to-reviews.md: each promise in the review decks versus what was built and tested, including anything that differs and why.
- docs/demo-script.md: a 5 minute faculty demo with exact commands.
- docs/viva.md: likely viva questions with short answers, including honest answers about limitations.

## Final report
Tell me exactly: what is implemented, what was tested (with results), what is deployed, what still needs manual action, and the exact commands I run to demonstrate the project.
