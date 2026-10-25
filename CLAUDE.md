# SDN-Based QoS Management for Video Streaming

College project (CSE student, moderate complexity). Keep everything explainable in a viva.

## What we are building
A Mininet + Open vSwitch network controlled by a Ryu (OpenFlow 1.3) controller. Video traffic is identified by port, link utilization is polled from port statistics, and when a link crosses a threshold the video flow is rerouted to an alternative path and placed in a priority queue. We compare a best-effort baseline against the QoS-enabled run and show real results on a React dashboard.

Requirements come from the two review decks in docs/requirements/. Read them with python-pptx before designing anything and keep the project aligned with them.

## Environment (decided, do not change without asking)
- Ubuntu 22.04 LTS VM in VMware Workstation, Python 3.10.
- Mininet and Open vSwitch are installed system-wide (apt or official source install).
- Ryu, Flask and other app dependencies live in a venv at ./.venv. Never use sudo pip.
- The Mininet topology script runs with sudo using the SYSTEM python3 (a venv is not visible under sudo). Ryu and Flask run as normal user from the venv, as separate processes.
- Ryu is old (last release 2020). If it fails on this Python, diagnose first. A known fix is pinning eventlet==0.30.2. Report any change to the Ryu plan.
- Node.js LTS + npm for the frontend.

## Repository layout
frontend/ backend/ sdn/ config/ scripts/ results/ docs/ README.md
docs/PROGRESS.md is the running log: update it at the end of every phase (done, tested, open issues, exact commands). Read it first in every new session.

## Architecture decisions
- Topology: client h1 and background host h3 on ingress switch s1, server h2 on egress switch s4. Path A: s1-s2-s4. Path B: s1-s3-s4. Bottleneck capacity is configurable (config/).
- Loops: the topology has a loop. No flooding learning switch. The controller installs explicit per-flow paths and handles ARP (or uses static ARP). Verify there is no broadcast storm.
- Bottleneck and priority queues: implemented with Open vSwitch QoS (linux-htb queues via ovs-vsctl) and OpenFlow set-queue actions. Do NOT also use Mininet TCLink bandwidth on the same interfaces, the two conflict.
- Metric sources: controller port stats give throughput, utilization and drop counters. Delay, jitter and loss come from the end hosts (ping, iperf3 UDP server report). Never claim the controller measured delay, jitter or loss.
- Video: iperf3 UDP on a configurable port (default 5004) acts as the video flow. Buffering is reported only if an instrumented client measured it, and then labelled as a playout buffer model, not a real player.
- Ryu pushes metrics and events to the Flask backend over HTTP on localhost. The dashboard only talks to Flask.
- Ports (all bound to 127.0.0.1 unless told otherwise): OpenFlow 6653, Ryu REST (if used) 8080, Flask 5000, Vite 5173.
- Anti-flap rules in the controller: threshold must be exceeded for N consecutive polls, there is a cooldown after any reroute, missing stats are logged and skipped, never reroute endlessly.

## Hard rules
1. Never present simulated numbers as experimental results. DEMO MODE data is clearly labelled everywhere it appears. LIVE MODE never silently falls back to demo data, it shows an error state instead.
2. Do not claim something works until it was run and verified. Do not claim priority queues work until configured and measured on the actual port.
3. Do not claim QoS improves every metric. Report what was measured, with limitations.
4. No machine learning, no reinforcement learning, no cloud infrastructure beyond Vercel for the frontend.
5. Never expose the OpenFlow port or any controller interface publicly. Do not touch firewall rules, SSH config or sudoers. Do not disable security protections.
6. Ask before any sudo command or system-level install. Otherwise keep working without stopping to ask. Never delete user data or overwrite existing config without confirmation.
7. If a command fails, read the real error and logs, then fix the actual cause. Do not repeat generic install commands.
8. Reuse what already works. Check before reinstalling or recreating anything.
9. Explain each major step briefly in plain words, I am a student and need to present this.
10. Do not use em dashes or en dashes in documents or generated text.
