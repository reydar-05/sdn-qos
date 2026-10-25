# Troubleshooting log

Real problems hit while setting up this lab, the exact error text, and
the actual fix applied. Kept so the same problem is never re-diagnosed
from scratch, and so it can be explained in a viva if asked.

## sudo needs an interactive terminal

**Symptom:** any `sudo <cmd>` run through an automated tool (including
Claude Code's own shell tool) fails with:
```
sudo: a terminal is required to read the password; either use the -S
option to read from standard input or configure an askpass helper
sudo: a password is required
```

**Cause:** sudo refuses to prompt for a password when it has no real
TTY attached, which an automated tool's piped shell does not provide.

**Fix:** run any command that needs sudo yourself, in a real terminal,
not through automation. This is why the scripts in scripts/ are meant to
be run directly by you, and why install/verification steps in this
project are always handed to you as exact commands to run and report
back on, instead of being run on your behalf.

**Not a fix:** do not add passwordless sudo (NOPASSWD) for this just to
make automation easier. That is a sudoers change, which this project's
rules explicitly forbid touching without being asked.

## Ryu install fails: `AttributeError: 'types.SimpleNamespace' object has no attribute 'get_script_args'`

**Cause:** Ryu's `setup.py` patches
`setuptools.command.easy_install.get_script_args` at import time.
setuptools >= 58 stubs that module out, so the attribute does not exist.

**Fix:** `pip install "setuptools<58"` in the venv, then install Ryu
with `--no-build-isolation` (otherwise pip builds Ryu in a fresh
isolated environment with the newest setuptools anyway, and the same
error comes back).

## `pip install ryu` silently installs version 2.2, which is broken on Python 3

**Symptom:** `pip show ryu` reports version 2.2 instead of the expected
4.34, and
```
AttributeError: module 'string' has no attribute 'upper'
```
when importing `ryu.ofproto.ofproto_v1_3`.

**Cause:** pip's dependency resolver, trying to satisfy an already
pinned `eventlet==0.30.2` in the venv, backtracked to the oldest "ryu"
release on PyPI that declares compatibility with it. Ryu 2.2 predates
Ryu's Python 3 port and still has Python 2 syntax
(`string.upper(x)` instead of `x.upper()`).

**Fix:** always pin the exact Ryu version explicitly
(`pip install ryu==4.34`), never let it resolve freely while eventlet
is already pinned.

## eventlet 0.30.2 crashes on Python 3.10.12: `TypeError: cannot set 'is_timeout' attribute of immutable type 'TimeoutError'`

**Cause:** eventlet tries to monkeypatch an `is_timeout` property onto
the built-in `TimeoutError` class (which `socket.timeout` is now an
alias of). This Python build treats that built-in type as immutable.

**Fix:** use eventlet **0.33.3**, not 0.30.2. Versions 0.31.0-0.32.0
still crash the same way; 0.33.0-0.33.2 fix this crash but introduce a
different one (see below). 0.33.3 is the first version that is clean on
this exact Python build.

## eventlet 0.33.0-0.33.2 + dnspython 1.16.0: `AttributeError: module 'collections' has no attribute 'MutableMapping'`

**Cause:** these eventlet versions still require `dnspython<2.0`, and
dnspython 1.16.0 uses `collections.MutableMapping`, which Python 3.10
removed (it moved to `collections.abc` in 3.3 and was deleted outright
in 3.10).

**Attempted fix that did NOT work:** forcing `dnspython>=2.0` on top of
eventlet 0.33.0-0.33.2 just trades this crash for another one,
`AttributeError: module 'dns.rdtypes' has no attribute 'tlsabase'`,
because those eventlet versions' DNS-patching code
(`eventlet/support/greendns.py`) was not yet updated for dnspython 2.x's
internal module layout.

**Actual fix:** use eventlet **0.33.3** together with `dnspython>=2.0`.
0.33.3's `greendns.py` was updated for dnspython 2.x, so this
combination is the first one that imports cleanly.

## eventlet 0.33.3 + Ryu: `ImportError: cannot import name 'ALREADY_HANDLED' from 'eventlet.wsgi'`

**Cause:** eventlet 0.33.3 removed the module-level `ALREADY_HANDLED`
sentinel from `eventlet.wsgi`, replacing it with a thread-local flag
(`WSGI_LOCAL.already_handled`). Ryu's own `ryu/app/wsgi.py` (last
touched in 2020) still imports the old symbol directly, and does so
unconditionally - this import is reached by any Ryu app, not just ones
that use Ryu's REST features.

**Fix:** patch the one place in the installed package that imports it.
In `.venv/lib/python3.10/site-packages/ryu/app/wsgi.py`, inside
`class _AlreadyHandledResponse`, the symbol is only ever used as an
opaque sentinel object for the `@websocket` decorator path (not used in
this project). Replaced:
```python
from eventlet.wsgi import ALREADY_HANDLED
_ALREADY_HANDLED = ALREADY_HANDLED
```
with:
```python
_ALREADY_HANDLED = object()
```
`scripts/install_lab_dependencies.sh` applies this patch automatically.
If you ever delete and recreate `.venv`, you need to either re-run that
script or redo this one-line edit by hand - plain `pip install
-r sdn/requirements.txt` alone will not reapply it.

## `npm create vite` hangs with no visible output

**Symptom:** `scripts/verify_environment.sh` appeared to hang forever
during the frontend check. The real cause, found by checking
`/tmp/vite_create.log` in a second terminal, was an interactive prompt
waiting for input that the script's output redirection had hidden:
first "Need to install the following packages: create-vite@9.3.1. Ok to
proceed? (y)", then (after adding `-y`) a second prompt, "Which linter
to use? Oxlint / ESLint".

**Cause:** `npm create vite@latest` is an interactive scaffolding
wizard. Recent versions added more questions (a linter choice) that
plain `-y` / `CI=true` did not reliably suppress in this npm/Node
version.

**Fix:** stopped using the interactive scaffolder for this
verification entirely. `scripts/verify_environment.sh` now writes a
minimal `package.json`, `vite.config.js`, `index.html` and two `.jsx`
files by hand, then just runs `npm install` and `npm run build` on
them. No wizard, nothing that can prompt.

## OVS QoS queues created correctly but iperf3 showed no rate limiting

**Symptom:** in the first run of `scripts/verify_queues.sh`, both the
"baseline" and "throttled" iperf3 runs measured 10-30+ Gbit/s - far
above the configured 2 Mbit/s low-queue cap. The QoS and queue objects
themselves looked correct in `ovs-vsctl list qos` / `list queue`.

**Cause:** a real mistake in the test, not a tool problem. `tc`/HTB
qdiscs rate-limit **egress** traffic on the interface they are attached
to. The test applies QoS to prove h1->h2 traffic gets limited, but the
QoS was attached to the switch port facing **h1** - that port's egress
only carries h2->h1 traffic (the reverse direction). The port that
h1->h2 traffic actually egresses through is the one facing **h2**.

**Fix:** `sdn/test_queues_topo.py` now attaches the QoS/queues to the
switch port facing the traffic's destination host, not its source.
After the fix, the low queue (ceil ~2Mbit) measurably throttled
throughput to ~1.9 Mbit/s (receiver) versus ~9.6 Mbit/s on the default
queue - see docs/environment-report.md for the full numbers.

**Lesson for the real controller (later phases):** when the Ryu
controller pushes an OpenFlow `set-queue` action for the video flow, it
must push it on the switch's output port toward the flow's destination,
for the same reason.

## QoS/queue cleanup silently did nothing, leaving orphaned OVSDB rows

**Symptom:** after `scripts/verify_queues.sh` ran (including its own
cleanup step), `sudo ovs-vsctl list qos` and `list queue` still showed
old rows from the test - 2 qos rows, 4 queue rows, unattached to any
port.

**Cause:** the cleanup command was `ovs-vsctl destroy qos -- --all`.
`--all` is a global flag ("destroy every row of this table") that
`ovs-vsctl` only recognizes **before** the command, not after a `--`
separator. Written the way it was, `-- --all` was parsed as a second,
invalid command, which failed - and the script didn't check the exit
code, so the failure was silent and the run reported success anyway.
Caught only by manually checking `ovs-vsctl list qos` after the fact,
before trusting the environment was clean enough to snapshot.

**Fix:** `sudo ovs-vsctl --all destroy qos` and `sudo ovs-vsctl --all
destroy queue` (flag before the command). Fixed in
`sdn/test_queues_topo.py` and `scripts/cleanup_lab.sh`, and the fixed
version now checks the exit code and warns if cleanup fails instead of
assuming success.

**Lesson:** a script reporting "cleanup complete" is not proof cleanup
happened - always independently check the real state
(`ovs-vsctl list qos`/`list queue`/`list-br`) after a test run, exactly
like checking CLAUDE.md's rule not to claim something works without
having verified it.


## Phase 1: switches never connected, Ryu silently disappeared

**Symptom:** `scripts/verify_phase1.sh` printed only
`Unable to contact the remote controller at 127.0.0.1:6653` and then
waited. The Ryu log showed a clean start and then nothing, with no
error or traceback, and `pgrep -af ryu-manager` found no process.

**Cause:** `sdn/topology.py` and `sdn/verify_phase1.py` ran `mn -c` at
startup to remove leftovers. Mininet's cleanup (`mininet/clean.py`) has
`ryu-manager` in its list of "zombie" controller processes and kills it
with `pkill -9`, so it killed the controller the wrapper had just
started. A `-9` kill leaves nothing in the log.

**Fix:** never run `mn -c` after Ryu is started. The Python scripts no
longer call it; the wrapper scripts run `sudo mn -c` first and then
start Ryu. The wrapper also checks at the end that Ryu is still alive,
and verify_phase1.py stops right away if the switches do not connect.

## Phase 3: iperf3 -R (reverse) UDP reports impossible loss numbers

**Symptom:** with `iperf3 -c ... -u -R` (server sends, client receives),
the JSON showed lost_packets 678736 in the first second, negative loss
(-345) in every later second, out_of_order equal to almost every packet,
and totals like "lost_percent 3196%". The received rate was still right
(2.77 Mbit/s under congestion) and the kernel HTB counters showed 11118
real drops.

**Cause (as observed):** the first datagram the receiver read carried a
huge, wrong sequence number, so every later, correctly numbered packet
was counted as out of order and the loss arithmetic went negative. Seen
with iperf3 3.9 in reverse mode only; the Phase 2 run happened to start
cleanly, so the problem is intermittent.

**Fix:** do not use -R. The receiver now runs `iperf3 -s -1 -J` on the
video client (h1) and background host (h3), and the iperf3 client runs on
h2 and sends. The server-side JSON is iperf3's normal receiver report.
The controller matches the video port as UDP source or destination, so
classification does not depend on which side opened the session.

## Phase 3: a single sender is still slowed down instead of dropped

**Symptom:** in the queue_only run the background (asked 9 Mbit/s)
received 5.73 Mbit/s with 0 drops in its queue, even with a 50-packet
queue limit. With two flows in one queue (baseline) drops did happen.

**Cause:** same shared-kernel effect as in Phase 2. One UDP socket can
only have about 40 packets in flight before the sender blocks; a
50-packet queue holding one flow's traffic never fills.

**Fix:** queue_limit_packets 25 (30 ms at 10 Mbit/s) and a new check that
each iperf3 sender actually sent at least 97% of its configured rate. If
that check fails, loss numbers from that run are not trusted.

## Phase 3: "queue buffer limit" check found no queues

**Cause:** `tc qdisc show` hides the FIFOs HTB creates under each class.
**Fix:** `tc qdisc show dev X invisible`. The limit itself was working:
baseline ping RTT sat at 58-61 ms, exactly 50 packets x 1500 bytes at
10 Mbit/s.

## Phase 3: video rate grew by ~4 Mbit/s every poll, reroute refused

**Symptom:** metrics showed video at 18, 22, 26, 30 ... Mbit/s on a 10
Mbit/s link; the qos run logged reroute_skipped reason=no_better_path
with predicted_with_video 3.07 (307%) for an idle Path B.

**Cause:** after video matching was changed to "port as source OR as
destination", each switch has two UDP video rules with the same
priority. The rate tracker key was (switch, priority), so the two rules
shared one entry: the idle rule's 0 bytes overwrote the busy rule's last
sample, and the next delta was the whole byte total since the start.

**Fix:** key on the rule's full match. Re-tested offline with two rules
(4.0 Mbit/s steady). The admission check itself behaved correctly: it
refused a move that its (wrong) input said would overload Path B.
