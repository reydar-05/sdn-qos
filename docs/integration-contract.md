# Integration contract

How the pieces run and talk to each other. All ports are bound to
127.0.0.1 only - nothing here is ever exposed outside the VM.

## Processes

| Process | Runs as | Interpreter | Notes |
|---|---|---|---|
| Mininet topology script | root (sudo) | **system** python3 | A venv is not visible under sudo, so this must use the system interpreter, not `.venv`. |
| Open vSwitch (`ovs-vswitchd`, `ovsdb-server`) | system service | n/a | Started by `systemctl`, independent of Mininet. |
| Ryu controller | normal user | `.venv/bin/python3` (via `ryu-manager`) | Separate process from Mininet and Flask. |
| Flask backend | normal user | `.venv/bin/python3` | Separate process from Ryu. |
| React/Vite dev server | normal user | Node.js | Talks only to Flask, never directly to Ryu or Mininet. |

## Data flow

```
Mininet/OVS (switches, hosts, links)
        | OpenFlow 1.3 (port 6653, localhost)
        v
Ryu controller
        | polls port stats (OFPPortStatsRequest/Reply)
        | decides reroute/priority actions
        | HTTP POST (localhost) with metrics/events
        v
Flask backend (port 5000, localhost)
        | HTTP GET (localhost)
        v
React dashboard (Vite dev server, port 5173, localhost)
```

- **Ryu is the only source of controller-side metrics** (throughput,
  utilization, drop counters) from OpenFlow port statistics.
- **Delay, jitter and loss come only from end hosts** (ping, iperf3 UDP
  server reports), never from the controller. Ryu never claims to have
  measured these.
- Ryu pushes to Flask; the dashboard never talks to Ryu or to Mininet
  directly. Flask is the single integration point for the frontend.

## Ports (all 127.0.0.1 only)

| Port | Used by | Purpose |
|---|---|---|
| 6653 | Ryu, OVS | OpenFlow 1.3 |
| 8080 | Ryu | Ryu's own REST API, only if an app in sdn/ enables it |
| 5000 | Flask | Backend API the dashboard reads |
| 5173 | Vite | React dev server |
| 5004 | iperf3 (UDP) | Simulated video flow, identified by this port |

## LIVE vs DEMO mode

- **DEMO mode:** data is pre-generated/simulated, and every view that
  shows it is clearly labelled as demo data.
- **LIVE mode:** data comes from a running Mininet/Ryu/Flask stack. If
  LIVE mode cannot get real data (a process is down, a request fails),
  it shows an explicit error state. It never silently falls back to
  demo data - that would misrepresent simulated numbers as real
  results, which this project's rules forbid.

## Start order

1. Open vSwitch service (should already be running as a system service;
   `systemctl is-active openvswitch-switch` to check).
2. Ryu controller (`.venv/bin/ryu-manager ...`), so it is listening on
   6653 before any switch tries to connect.
3. Mininet topology (`sudo python3 sdn/<topology_script>.py`), which
   connects its OVS switches to the already-running Ryu controller.
4. Flask backend (`.venv/bin/python3 backend/app.py` or equivalent).
5. React dev server (`npm run dev` in `frontend/`).

## Stop order (reverse of start)

1. Stop the React dev server (Ctrl+C).
2. Stop Flask (Ctrl+C).
3. Tear down the Mininet topology (`sudo mn -c`, or exit the topology
   script's CLI if it has one).
4. Stop Ryu (Ctrl+C, or `pkill -f ryu-manager`).
5. Open vSwitch service can stay running; it is a shared system service.

`scripts/cleanup_lab.sh` automates steps 3-4 plus leftover OVS QoS/queue
cleanup, for when something was left running after a crashed test.
