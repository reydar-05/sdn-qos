# Installation guide

This is the exact sequence used to set up the lab on Ubuntu 22.04 LTS in
a VMware Workstation VM. Follow it in order on a fresh VM. Every command
that touches the system is also in scripts/install_lab_dependencies.sh,
which is idempotent (safe to re-run, skips what is already installed).

Everything here runs in a normal terminal with an interactive login, not
through an automation tool, because `sudo` needs to prompt for your
password.

## 1. System packages

```
sudo apt-get update
sudo apt-get install -y python3.10-venv python3-pip python3-dev
sudo apt-get install -y mininet
sudo apt-get install -y openvswitch-switch
sudo systemctl enable --now openvswitch-switch
sudo apt-get install -y iperf3 net-tools ffmpeg
```

`build-essential`, `curl`, `git`, `iproute2` (tc), `iputils-ping`, and
`tcpdump` are part of a standard Ubuntu 22.04 desktop/server install and
need no extra step, but check with `dpkg -l <pkg>` if you are on a
minimal image.

Mininet (2.3.0) and Open vSwitch (2.17.x) both come from Ubuntu 22.04's
own apt repositories and do not need the official source installer.

## 2. Node.js LTS

Ubuntu 22.04's own apt repo only ships Node 12, which is too old for a
current Vite/React app. Use the official NodeSource setup script, which
installs whichever release is the current LTS line:

```
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt-get install -y nodejs
node -v
npm -v
```

## 3. Python virtual environment

Create the venv with the **system** python3 (3.10), then install
packages into it. Never use `sudo pip`.

```
cd ~/sdn-qos
python3 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
```

### 3a. Ryu - two real compatibility problems and their fixes

Ryu's last release (4.34, from 2020) does not install cleanly on a
modern Python 3.10 + pip + setuptools stack. Two separate problems, both
diagnosed by actually reading the tracebacks rather than guessing:

**Problem 1: setuptools is too new.**
Ryu's `setup.py` patches `setuptools.command.easy_install.get_script_args`
at import time. setuptools >= 58 no longer exposes that attribute, so
the build crashes immediately with:
`AttributeError: 'types.SimpleNamespace' object has no attribute 'get_script_args'`

Fix: pin setuptools below 58 in the venv, and install Ryu with
`--no-build-isolation` so it actually uses that pinned version instead
of letting pip build Ryu in a fresh isolated environment with the
newest setuptools.

```
.venv/bin/pip install "setuptools<58"
.venv/bin/pip install --no-build-isolation ryu==4.34
```

**Problem 2: eventlet==0.30.2 (the commonly suggested pin) crashes on
this exact Python 3.10.12.** It tries to monkeypatch an `is_timeout`
attribute onto the built-in `TimeoutError` type, which this Python
treats as immutable:
`TypeError: cannot set 'is_timeout' attribute of immutable type 'TimeoutError'`

Later eventlet versions fix this, but introduce two more problems of
their own that had to be worked through one at a time:
- eventlet 0.31.0-0.32.0 fix nothing new (same crash).
- eventlet 0.33.0-0.33.2 fix the TimeoutError crash, but still pin
  `dnspython<2.0`, and dnspython 1.16.0 uses `collections.MutableMapping`,
  removed in Python 3.10 (`AttributeError: module 'collections' has no
  attribute 'MutableMapping'`). Forcing `dnspython>=2.0` on top of these
  just moves the crash somewhere else: eventlet's DNS-patching code
  (`greendns.py`) in these versions isn't written for dnspython 2.x's
  internal module layout either.
- **eventlet 0.33.3** fixes both at once: the TimeoutError bug, and its
  `greendns.py` was updated for dnspython 2.x. This is the version that
  actually works here.

```
.venv/bin/pip install "eventlet==0.33.3" "dnspython>=2.0"
```

**Problem 3 (caused by fixing problem 2): eventlet 0.33.3 removed the**
**`ALREADY_HANDLED` sentinel from `eventlet.wsgi`**, replacing it with a
thread-local flag. Ryu's own `ryu/app/wsgi.py` (unmaintained since 2020)
still does `from eventlet.wsgi import ALREADY_HANDLED`, which now fails
with `ImportError`. This import happens unconditionally whenever any Ryu
app does `from ryu.base import app_manager` - you cannot avoid it by
simply not using Ryu's REST features.

The only use of that symbol in Ryu's code is as an opaque sentinel
object for one niche feature (the `@websocket` decorator), which this
project does not use. The fix is a one-line patch to the installed
package in the venv, replacing the import with a locally-defined
sentinel object:

```python
# .venv/lib/python3.10/site-packages/ryu/app/wsgi.py, inside
# class _AlreadyHandledResponse:
#
# before:
#     from eventlet.wsgi import ALREADY_HANDLED
#     _ALREADY_HANDLED = ALREADY_HANDLED
#
# after:
#     _ALREADY_HANDLED = object()
```

`scripts/install_lab_dependencies.sh` applies this patch automatically
right after installing Ryu. See docs/troubleshooting.md if you ever
recreate the venv and need to redo it by hand.

The final, working pin set is recorded in `sdn/requirements.txt`.

### 3b. Flask backend and docs tooling

```
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/pip install -r scripts/requirements-docs.txt
```

## 4. Verify everything

```
bash scripts/inspect_environment.sh
bash scripts/verify_environment.sh
bash scripts/test_mininet.sh
bash scripts/verify_controller.sh
bash scripts/verify_queues.sh
```

Real output from these runs on this VM is recorded in
docs/environment-report.md.

## 5. Clean up after any test

```
bash scripts/cleanup_lab.sh
```
