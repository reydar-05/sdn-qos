# PHASE 0 PROMPT: Environment setup (paste into Claude Code, inside ~/sdn-qos)

Read CLAUDE.md first. It has the project rules and decisions.

Your job in this phase is ONLY to prepare and verify the Linux lab. Do not build the project yet.

I am inside an Ubuntu 22.04 VM (VMware Workstation). Do not assume you have root: use sudo only after telling me what the command does and getting my approval. Start by checking whether docs/environment-report.md already exists and reuse any existing scripts or venv.

## Step 1: Inspect (no changes yet)
Report: Ubuntu version, kernel, CPU cores, RAM, free disk, whether this is a VM, Python/pip versions, git, Node/npm, and whether these are installed: mininet, openvswitch-switch (and whether the service is running), ryu, iperf3, tc (iproute2). Check that network namespaces and veth work (for example `sudo ip netns add t && sudo ip netns del t`, with my approval). Give me a short summary and the install plan before changing anything.

## Step 2: Install system packages (with my approval, one group at a time)
- Build tools, git, curl, python3-venv, python3-dev, pip.
- Mininet (apt package is fine on 22.04, or the official source install from https://mininet.org/download/ if apt fails).
- openvswitch-switch, and make sure the service is enabled and running.
- iperf3, iputils-ping, iproute2, net-tools, tcpdump, ffmpeg (optional, for a real video test later).
- Node.js LTS and npm (from https://nodejs.org/en/download or NodeSource, explain which you choose).

## Step 3: Python environment
Create ./.venv. Install Ryu and Flask (plus flask-cors, requests, python-pptx) in it. Ryu docs: https://ryu.readthedocs.io/en/latest/getting_started.html . If Ryu fails to run on Python 3.10, diagnose the exact error. The usual cause is eventlet, try pinning eventlet==0.30.2. Save working versions in backend/requirements.txt and sdn/requirements.txt. Do not use sudo pip.

## Step 4: Verify each component separately and show me the real output
1. `sudo mn --test pingall` must show 0% dropped. Clean up with `sudo mn -c`.
2. Open vSwitch: `ovs-vsctl --version`, `sudo ovs-vsctl show`, service status.
3. Ryu: write a minimal OpenFlow 1.3 app in sdn/ (a simple learning switch is fine for this test only). Start it, start a Mininet topology with `--controller=remote,ip=127.0.0.1,port=6653 --switch ovsk,protocols=OpenFlow13`, confirm the switch connected (Ryu logs the datapath), and that pingall passes through the controller.
4. iperf3: run a local server and client, show the throughput line.
5. tc / HTB: confirm tc exists and the htb qdisc can be created on a veth or Mininet interface, then remove it.
6. OVS queues (important): in a small Mininet test, create a linux-htb QoS with two queues on a switch port using ovs-vsctl, show it with `ovs-vsctl list qos` and `list queue`, then run iperf3 through the port and show that the queue limits actually apply. Only if this is measured may you say queues work. If it fails, report the exact error and the simplest fix.
7. Frontend prerequisites: `node -v`, `npm -v`, and create a throwaway Vite React app in a temp folder to confirm `npm install` and `npm run build` work, then delete it.
8. Flask: start a tiny hello app in the venv and curl it on 127.0.0.1:5000.

## Step 5: Create the workspace
scripts/: inspect_environment.sh, install_lab_dependencies.sh, verify_environment.sh, test_mininet.sh, verify_controller.sh, verify_queues.sh, cleanup_lab.sh. Each script must be repeatable, detect existing installs, stop on real errors, print clear messages, mark which commands need sudo, and never touch firewall, SSH or sudoers.
docs/: installation-guide.md, environment-report.md, troubleshooting.md, integration-contract.md.
config/environment.example.env

## Step 6: Integration contract (docs/integration-contract.md)
Describe where each part runs and how they talk: Ryu, Mininet/OVS, Flask, React dev server, which process collects statistics, how metrics reach Flask, how the dashboard reads them, how LIVE differs from DEMO, the ports and that they are localhost only, and the exact start and stop order and commands.

## Step 7: Handoff report (docs/environment-report.md)
A table with columns: Component, Required version, Detected version, Install status, Verification test, Test result, Remaining issue. Classify each as: 1 Installed and verified, 2 Installed but not verified, 3 Missing, 4 Blocked. Give the exact commands for anything left. Also update docs/PROGRESS.md.

Do not claim anything succeeded unless you ran the check and saw it pass. When finished, summarise in plain words and stop. I will say "continue" for the next phase.
