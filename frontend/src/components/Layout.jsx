import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { Activity, FlaskConical, Gauge, Network, ScrollText, Settings2, Radio, PlayCircle } from 'lucide-react'
import { useMode } from '../lib/mode'
import { useData } from '../lib/useData'
import { DEMO_FILE } from '../demo/demoData'

const NAV = [
  { to: '/', label: 'Overview', Icon: Gauge, end: true },
  { to: '/topology', label: 'Topology', Icon: Network },
  { to: '/monitoring', label: 'QoS monitoring', Icon: Activity },
  { to: '/experiments', label: 'Experiments', Icon: FlaskConical },
  { to: '/events', label: 'Event logs', Icon: ScrollText },
]

function ModeSwitch() {
  const { mode, setMode } = useMode()
  const btn = (m, label, Icon) => (
    <button type="button" onClick={() => setMode(m)} aria-pressed={mode === m}
      className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
        mode === m ? 'bg-surface text-ink shadow-sm' : 'text-ink-2 hover:text-ink'}`}>
      <Icon className="h-3.5 w-3.5" aria-hidden /> {label}
    </button>
  )
  return (
    <div className="inline-flex rounded-lg bg-surface-2 p-0.5" role="group" aria-label="Data mode">
      {btn('live', 'LIVE LAB', Radio)}
      {btn('demo', 'DEMO MODE', PlayCircle)}
    </div>
  )
}

/** Permanent banner: always says which data the page shows. */
function ModeBanner() {
  const { isDemo, apiBase } = useMode()
  const status = useData('status', { interval: 3000, enabled: !isDemo })
  if (isDemo) {
    return (
      <div className="border-b border-warning bg-demo-bg px-4 py-2 text-xs text-demo-ink sm:text-sm" role="status">
        <strong className="font-bold tracking-wide">DEMO MODE: </strong>
        every number on these pages is invented sample data from <code className="font-mono">{DEMO_FILE}</code>.
        It is not an experimental result. Switch to LIVE LAB for real data from the lab.
      </div>
    )
  }
  let text, cls
  if (status.loading && !status.data) {
    text = `connecting to the backend at ${apiBase}`
    cls = 'bg-surface-2 text-ink-2 border-line'
  } else if (status.error) {
    text = `backend not reachable at ${apiBase}: ${status.error.message}`
    cls = 'bg-error-bg text-error-ink border-critical'
  } else if (!status.data.controller.reachable) {
    text = `backend OK at ${apiBase}, but the Ryu controller is not sending data (${status.data.controller.reason}). Recorded experiment results are still available.`
    cls = 'bg-error-bg text-error-ink border-critical'
  } else {
    text = `real data from the backend at ${apiBase}; controller connected, mode ${status.data.mode || 'unknown'}`
    cls = 'bg-live-bg text-live-ink border-good'
  }
  return (
    <div className={`border-b px-4 py-2 text-xs sm:text-sm ${cls}`} role="status">
      <strong className="font-bold tracking-wide">LIVE LAB: </strong>{text}
    </div>
  )
}

function ConnectionPanel() {
  const { isDemo, apiBase, setApiBase, token, setToken } = useMode()
  const [open, setOpen] = useState(false)
  const [base, setBase] = useState(apiBase)
  const [tok, setTok] = useState(token)
  if (isDemo) return null
  return (
    <div className="relative">
      <button type="button" onClick={() => { setOpen(!open); setBase(apiBase); setTok(token) }}
        className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1.5 text-xs text-ink-2 hover:bg-surface-2"
        aria-expanded={open}>
        <Settings2 className="h-3.5 w-3.5" aria-hidden /> Connection
      </button>
      {open && (
        <form className="absolute right-0 z-20 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-lg border border-line bg-surface p-3 shadow-lg"
          onSubmit={(e) => { e.preventDefault(); setApiBase(base); setToken(tok.trim()); setOpen(false) }}>
          <label className="block text-xs font-medium text-ink-2" htmlFor="api-base">Backend URL</label>
          <input id="api-base" value={base} onChange={(e) => setBase(e.target.value)}
            className="mt-1 w-full rounded border border-line bg-page px-2 py-1 text-sm text-ink" />
          <label className="mt-3 block text-xs font-medium text-ink-2" htmlFor="api-token">API token (only if the backend sets SDN_QOS_API_TOKEN)</label>
          <input id="api-token" type="password" value={tok} onChange={(e) => setTok(e.target.value)} autoComplete="off"
            className="mt-1 w-full rounded border border-line bg-page px-2 py-1 text-sm text-ink" />
          <p className="mt-2 text-[11px] text-ink-3">Saved in this browser only. The token is never part of the site build.</p>
          <div className="mt-3 flex justify-end gap-2">
            <button type="button" onClick={() => setOpen(false)} className="rounded px-2 py-1 text-xs text-ink-2 hover:bg-surface-2">Cancel</button>
            <button type="submit" className="rounded bg-qos px-3 py-1 text-xs font-semibold text-white">Save</button>
          </div>
        </form>
      )}
    </div>
  )
}

export default function Layout() {
  return (
    <div className="min-h-screen bg-page">
      <div className="sticky top-0 z-10">
        <ModeBanner />
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
            <div className="flex items-center gap-2">
              <img src="/favicon.svg" alt="" className="h-7 w-7" />
              <div>
                <p className="text-sm font-semibold leading-tight text-ink">SDN QoS for video streaming</p>
                <p className="text-[11px] leading-tight text-ink-3">Mininet, Open vSwitch, Ryu (OpenFlow 1.3)</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <ConnectionPanel />
              <ModeSwitch />
            </div>
          </div>
          <nav className="mx-auto max-w-7xl overflow-x-auto px-2" aria-label="Pages">
            <ul className="flex gap-1">
              {NAV.map(({ to, label, Icon, end }) => (
                <li key={to}>
                  <NavLink to={to} end={end}
                    className={({ isActive }) => `inline-flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm ${
                      isActive ? 'border-qos font-semibold text-ink' : 'border-transparent text-ink-2 hover:text-ink'}`}>
                    <Icon className="h-4 w-4" aria-hidden /> {label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        </header>
      </div>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-8 text-xs text-ink-3">
        Emulated network on one VM (Mininet). Delay, jitter and loss are measured on the end hosts, never by the controller.
        Buffering numbers come from a playout buffer model, not a real video player.
      </footer>
    </div>
  )
}
