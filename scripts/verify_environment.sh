#!/usr/bin/env bash
# Phase 0, Step 4 (parts 2, 4, 5, 7, 8): verify components that do NOT
# need a full Mininet+controller run. Mininet/controller/queue tests live
# in their own scripts (test_mininet.sh, verify_controller.sh,
# verify_queues.sh) because they need more setup and cleanup.
# Some commands below need sudo and will prompt you.
set -uo pipefail
cd "$(dirname "$0")/.."

pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; }

echo "=== 2. Open vSwitch ==="
ovs-vsctl --version
if sudo ovs-vsctl show >/tmp/ovs_show.txt 2>&1; then
  cat /tmp/ovs_show.txt
  pass "ovs-vsctl show"
else
  fail "ovs-vsctl show"; cat /tmp/ovs_show.txt
fi
echo "Service status: $(systemctl is-active openvswitch-switch)"
rm -f /tmp/ovs_show.txt

echo
echo "=== 4. iperf3 (local loopback test) ==="
iperf3 -s -D -1 >/tmp/iperf3_server.log 2>&1
sleep 1
if iperf3 -c 127.0.0.1 -t 3 | tee /tmp/iperf3_client.log | grep -q "sender"; then
  pass "iperf3 local throughput test"
else
  fail "iperf3 local throughput test"; cat /tmp/iperf3_client.log
fi
rm -f /tmp/iperf3_server.log /tmp/iperf3_client.log

echo
echo "=== 5. tc / HTB on a throwaway veth pair (requires sudo) ==="
sudo ip link add veth-qa type veth peer name veth-qb 2>/tmp/tc_err
if [ $? -eq 0 ]; then
  sudo ip link set veth-qa up
  if sudo tc qdisc add dev veth-qa root handle 1: htb default 10 2>>/tmp/tc_err \
     && sudo tc class add dev veth-qa parent 1: classid 1:10 htb rate 10mbit 2>>/tmp/tc_err; then
    pass "htb qdisc + class created on veth"
    sudo tc qdisc show dev veth-qa
  else
    fail "htb qdisc/class creation"; cat /tmp/tc_err
  fi
  sudo ip link del veth-qa 2>/dev/null
else
  fail "veth pair creation"; cat /tmp/tc_err
fi
rm -f /tmp/tc_err

echo
echo "=== 7. Frontend prerequisites (Node/npm, throwaway Vite app) ==="
node -v
npm -v
TMPDIR_VITE=$(mktemp -d)
echo "Creating a throwaway Vite+React project by hand in $TMPDIR_VITE ..."
echo "(skips the interactive 'npm create vite' scaffolding wizard entirely,"
echo " so there is nothing left to prompt)"
mkdir -p "$TMPDIR_VITE/testapp/src"
cat > "$TMPDIR_VITE/testapp/package.json" <<'JSONEOF'
{
  "name": "testapp",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": { "build": "vite build" },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "vite": "^5.4.0"
  }
}
JSONEOF
cat > "$TMPDIR_VITE/testapp/vite.config.js" <<'JSEOF'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({ plugins: [react()] })
JSEOF
cat > "$TMPDIR_VITE/testapp/index.html" <<'HTMLEOF'
<!doctype html>
<html>
<head><meta charset="UTF-8" /></head>
<body>
<div id="root"></div>
<script type="module" src="/src/main.jsx"></script>
</body>
</html>
HTMLEOF
cat > "$TMPDIR_VITE/testapp/src/main.jsx" <<'JSXEOF'
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
ReactDOM.createRoot(document.getElementById('root')).render(<App />)
JSXEOF
cat > "$TMPDIR_VITE/testapp/src/App.jsx" <<'JSXEOF'
export default function App() {
  return <h1>environment check</h1>
}
JSXEOF

(cd "$TMPDIR_VITE/testapp" && npm install >/tmp/vite_install.log 2>&1 && npm run build >/tmp/vite_build.log 2>&1)
if [ -d "$TMPDIR_VITE/testapp/dist" ]; then
  pass "npm install + npm run build produced dist/"
else
  fail "npm run build"; tail -30 /tmp/vite_install.log /tmp/vite_build.log
fi
rm -rf "$TMPDIR_VITE" /tmp/vite_install.log /tmp/vite_build.log

echo
echo "=== 8. Flask hello-world app on 127.0.0.1:5000 ==="
cat > /tmp/flask_hello.py <<'PYEOF'
from flask import Flask
app = Flask(__name__)

@app.route("/")
def hello():
    return "hello from flask"

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
PYEOF
.venv/bin/python3 /tmp/flask_hello.py > /tmp/flask_hello.log 2>&1 &
FLASK_PID=$!
sleep 2
if curl -s http://127.0.0.1:5000/ | grep -q "hello from flask"; then
  pass "Flask responded on 127.0.0.1:5000"
else
  fail "Flask did not respond as expected"; cat /tmp/flask_hello.log
fi
kill "$FLASK_PID" 2>/dev/null
rm -f /tmp/flask_hello.py /tmp/flask_hello.log

echo
echo "Verification pass complete. See PASS/FAIL markers above."
