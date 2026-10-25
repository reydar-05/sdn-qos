#!/usr/bin/env bash
# Phase 0, Step 2: install the system packages the lab needs.
# Safe to re-run: every group checks whether it is already installed
# before touching anything. Run as your normal user, not with sudo -
# the script calls sudo itself only for the commands that need it, and
# will prompt you for your password each time.
set -uo pipefail

need_pkg() { dpkg -l "$1" 2>/dev/null | grep -q "^ii"; }

echo "This will run several 'sudo apt-get install' groups, one at a time."
echo "You will be asked for your password by sudo when needed."
read -p "Continue? [y/N] " ans
case "$ans" in
  [Yy]*) ;;
  *) echo "Aborted, nothing changed."; exit 1 ;;
esac

echo; echo "== apt-get update =="
sudo apt-get update

echo; echo "== Python tooling (venv, pip, dev headers) =="
PKGS=""
need_pkg python3.10-venv || PKGS="$PKGS python3.10-venv"
need_pkg python3-pip || PKGS="$PKGS python3-pip"
need_pkg python3-dev || PKGS="$PKGS python3-dev"
if [ -n "$PKGS" ]; then
  sudo apt-get install -y $PKGS
else
  echo "already installed, skipping"
fi

echo; echo "== Mininet =="
if need_pkg mininet; then
  echo "already installed, skipping"
else
  sudo apt-get install -y mininet
fi

echo; echo "== Open vSwitch =="
if need_pkg openvswitch-switch; then
  echo "already installed"
else
  sudo apt-get install -y openvswitch-switch
fi
sudo systemctl enable --now openvswitch-switch
echo "openvswitch-switch service: $(systemctl is-active openvswitch-switch)"

echo; echo "== Test / capture tools (iperf3, net-tools, ffmpeg) =="
PKGS=""
need_pkg iperf3 || PKGS="$PKGS iperf3"
need_pkg net-tools || PKGS="$PKGS net-tools"
need_pkg ffmpeg || PKGS="$PKGS ffmpeg"
if [ -n "$PKGS" ]; then
  sudo apt-get install -y $PKGS
else
  echo "already installed, skipping"
fi

echo; echo "== Node.js LTS (via NodeSource, Ubuntu's own repo only has Node 12) =="
if command -v node >/dev/null 2>&1; then
  echo "node already installed: $(node -v)"
else
  curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

echo; echo "== Python virtual environment (.venv) =="
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python3 ]; then
  echo ".venv already exists, skipping creation"
else
  python3 -m venv .venv
fi

.venv/bin/pip install --upgrade pip wheel
# setuptools must stay below 58: ryu's legacy setup.py patches
# setuptools.command.easy_install.get_script_args, which modern
# setuptools no longer exposes.
.venv/bin/pip install "setuptools<58"

if .venv/bin/python3 -c "import ryu" >/dev/null 2>&1; then
  echo "ryu already installed, skipping"
else
  # --no-build-isolation: without it, pip builds ryu in a fresh isolated
  # env with the newest setuptools, which breaks the same way as above.
  .venv/bin/pip install --no-build-isolation -r sdn/requirements.txt
  WSGI_FILE=".venv/lib/python3.10/site-packages/ryu/app/wsgi.py"
  if grep -q "from eventlet.wsgi import ALREADY_HANDLED" "$WSGI_FILE" 2>/dev/null; then
    echo "Patching ryu/app/wsgi.py for eventlet>=0.33.3 compatibility..."
    python3 - "$WSGI_FILE" <<'PYEOF'
import sys
path = sys.argv[1]
old = (
    "    # XXX: Eventlet API should not be used directly.\n"
    "    from eventlet.wsgi import ALREADY_HANDLED\n"
    "    _ALREADY_HANDLED = ALREADY_HANDLED\n"
)
new = (
    "    # XXX: Eventlet API should not be used directly.\n"
    "    # eventlet>=0.33.3 removed the ALREADY_HANDLED sentinel in favor of a\n"
    "    # thread-local flag (WSGI_LOCAL.already_handled), so define our own\n"
    "    # sentinel here. Only affects the @websocket decorator path, unused\n"
    "    # in this project.\n"
    "    _ALREADY_HANDLED = object()\n"
)
text = open(path).read()
if old in text:
    open(path, "w").write(text.replace(old, new))
    print("patched")
else:
    print("pattern not found, leaving file untouched - check manually")
PYEOF
  fi
fi

if .venv/bin/python3 -c "import flask" >/dev/null 2>&1; then
  echo "flask already installed, skipping"
else
  .venv/bin/pip install -r backend/requirements.txt
fi

if .venv/bin/python3 -c "import pptx" >/dev/null 2>&1; then
  echo "python-pptx already installed, skipping"
else
  .venv/bin/pip install -r scripts/requirements-docs.txt
fi

echo
echo "Done. Run scripts/verify_environment.sh next to confirm everything works."
