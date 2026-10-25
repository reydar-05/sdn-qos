/* What to check when LIVE LAB data is missing. */
export function BackendHint() {
  return (
    <div>
      Start the backend from the project folder: <code className="font-mono">.venv/bin/python backend/app.py</code>.
      If the dashboard runs on another origin, add it to <code className="font-mono">SDN_QOS_CORS_ORIGINS</code>.
    </div>
  )
}

export function ControllerHint() {
  return (
    <div>
      The backend is up but Ryu has not pushed metrics recently. Start the lab (Ryu controller and the Mininet
      topology) and check that <code className="font-mono">SDN_QOS_BACKEND_URL</code> is not set to <code className="font-mono">off</code>.
    </div>
  )
}
