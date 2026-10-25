# Environment report

VM: Ubuntu 22.04.5 LTS, kernel 6.8.0-138-generic, VMware Workstation
guest, 4 CPU cores, 5.8 GiB RAM, 24-25 GiB disk free. Python 3.10.12.

Status key: **1** installed and verified, **2** installed but not
verified, **3** missing, **4** blocked.

| Component | Required version | Detected version | Install status | Verification test | Test result | Remaining issue |
|---|---|---|---|---|---|---|
| Ubuntu / kernel | 22.04 LTS | 22.04.5, kernel 6.8.0-138 | 1 | `lsb_release -a`, `uname -a` | Pass | None |
| VMware VM | - | confirmed (`systemd-detect-virt` -> vmware) | 1 | `systemd-detect-virt` | Pass | None |
| CPU / RAM / disk | moderate | 4 cores, 5.8 GiB RAM, ~24 GiB free | 1 | `nproc`, `free -h`, `df -h` | Pass, adequate for this project's scale | Watch RAM under load (Mininet + Ryu + Flask + Vite + browser together); close unused apps if things get slow |
| git | any recent | 2.34.1 | 1 | `git --version` | Pass | None |
| Python 3 | 3.10 | 3.10.12 | 1 | `python3 --version` | Pass | None |
| python3-venv / pip / dev | - | installed | 1 | `python3 -m venv --help`, `pip --version` | Pass | None |
| Mininet | 2.3.x (apt) | 2.3.0 | 1 | `mn --version`, `scripts/test_mininet.sh` | Pass - `sudo mn --test pingall`: 0% dropped | None |
| Open vSwitch | 2.17.x (apt) | 2.17.12, service active | 1 | `ovs-vsctl --version`, `systemctl is-active`, `sudo ovs-vsctl show` | Pass | None |
| Ryu | last release, 4.34 | 4.34 (in `.venv`) | 1 | `ryu-manager --version`, `scripts/verify_controller.sh` | Pass - switch connected (dpid=1), pingall through the controller 0% dropped | Needed 3 compatibility fixes for Python 3.10 (setuptools pin, eventlet pin, one-line patch to `ryu/app/wsgi.py`). Documented in docs/troubleshooting.md and docs/installation-guide.md. All fixes are applied in this venv and automated in `scripts/install_lab_dependencies.sh`. |
| eventlet | pinned for Ryu | 0.33.3 (not the commonly suggested 0.30.2 - that version crashes on this exact Python 3.10.12) | 1 | import test, controller run | Pass | None - but this is a deviation from the eventlet==0.30.2 fix mentioned in CLAUDE.md, reported here as required |
| Flask / flask-cors / requests | any recent | Flask 3.1.3, requests 2.34.2 | 1 | `scripts/verify_environment.sh` step 8, hello-world app on 127.0.0.1:5000 | Pass | None |
| iperf3 | any recent | 3.9 | 1 | local loopback throughput test | Pass | None |
| tc / iproute2 | any recent | iproute2-5.15.0 | 1 | htb qdisc+class created on a throwaway veth pair | Pass | None |
| OVS QoS queues (linux-htb) | - | - | 1 | `scripts/verify_queues.sh`: 2 queues created, measured with iperf3 | Pass (after fixing a port-direction mistake - see below) | Measured with TCP iperf3, which reacted with bursty/zero-throughput intervals under the sudden rate cut (normal TCP congestion-control behaviour, not a tool fault). Real priority-queue tests in later phases should use UDP iperf3, since that is what the actual video flow uses, and will give cleaner steady-state numbers. |
| Node.js | LTS | v24.22.1 (npm 11.19.1) | 1 | `node -v`, `npm -v`, throwaway Vite+React `npm install && npm run build` | Pass | None |
| python-pptx | any recent | 1.0.2 (via `scripts/requirements-docs.txt`) | 1 | `import pptx` | Pass | Not read yet - reading docs/requirements/*.pptx is the first task of the next phase, not this one |

## OVS QoS queue measurement (detail)

Two queues created on an OVS linux-htb QoS object:
- Queue 0 (default): min-rate 8 Mbit/s, max-rate 10 Mbit/s
- Queue 1 (low): min-rate 1 Mbit/s, max-rate 2 Mbit/s

First attempt measured no difference at all (both runs 10+ Gbit/s)
because the QoS was attached to the wrong switch port - see
docs/troubleshooting.md for the full diagnosis. After moving it to the
correct port (facing the traffic's destination host, since tc/htb
limits egress traffic), measured with iperf3 TCP, 5-second runs:

- Default queue (no tc filter): sender 12.4 Mbit/s, receiver 9.56 Mbit/s
- Forced into the low queue (`tc filter ... flowid 1:2`): sender
  4.45 Mbit/s, receiver 1.94 Mbit/s over a longer, bursty 5.95s window
  (TCP backed off hard after the sudden rate cut, including two
  0 bit/s one-second intervals)

This is a real, measured difference consistent with the configured
queue caps, not a simulated number. It is not a clean, noise-free
curve - that is flagged above as a remaining issue to address with UDP
traffic in later phases.

## Deviation from CLAUDE.md's suggested Ryu fix

CLAUDE.md names `eventlet==0.30.2` as "a known fix" if Ryu fails. That
exact pin crashes immediately on this VM's Python 3.10.12 with a
different, unrelated bug (eventlet trying to monkeypatch the built-in
`TimeoutError` type, which this Python treats as immutable). Diagnosed
the real cause before changing anything, then bisected eventlet
versions by hand: 0.31.0-0.32.0 have the same crash; 0.33.0-0.33.2 fix
it but break on dnspython's module layout; **0.33.3** is the first
version that is clean on both fronts, and is what is actually pinned in
`sdn/requirements.txt`. Fixing that then exposed one more issue (Ryu's
`wsgi.py` importing a sentinel eventlet 0.33.3 no longer exports), fixed
with a one-line patch to the installed package - full detail in
docs/troubleshooting.md.

## Not part of this phase

- docs/requirements/*.pptx have not been read yet. That is explicitly
  the first step of the next phase (design), not this environment-setup
  phase.
- No application code (topology script, real controller, Flask routes,
  React UI) has been written. This phase only set up and verified the
  lab itself.
