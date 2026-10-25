import { useState } from 'react'
import { AlertTriangle, ArrowRightLeft, CheckCircle2, Info, XCircle } from 'lucide-react'
import { Card, ErrorState, Loading, PageHeader } from '../components/ui'
import { BackendHint } from '../components/LiveHints'
import { useData } from '../lib/useData'
import { clock } from '../lib/format'

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'congestion', label: 'Congestion' },
  { key: 'route', label: 'Route changes' },
  { key: 'error', label: 'Errors and warnings' },
]

function category(ev) {
  const e = ev.event || ''
  if (e.startsWith('congestion')) return 'congestion'
  if (e.startsWith('reroute') || e === 'flows_installed') return e === 'reroute_unconfirmed' ? 'error' : 'route'
  if (/missing|error|fail|lost|unknown|timeout/.test(e)) return 'error'
  return 'other'
}

function icon(ev) {
  const e = ev.event
  if (e === 'congestion_detected') return <AlertTriangle className="h-4 w-4 text-critical-ink" aria-label="warning" />
  if (e === 'congestion_cleared' || e === 'reroute_confirmed') return <CheckCircle2 className="h-4 w-4 text-good-ink" aria-label="ok" />
  if (e === 'reroute') return <ArrowRightLeft className="h-4 w-4 text-ink" aria-label="route change" />
  if (category(ev) === 'error') return <XCircle className="h-4 w-4 text-critical-ink" aria-label="error" />
  return <Info className="h-4 w-4 text-ink-3" aria-label="info" />
}

function describe(ev) {
  switch (ev.event) {
    case 'congestion_detected': return `${ev.link} above ${ev.threshold} for ${ev.polls} polls (utilization ${ev.utilization})${ev.on_video_path ? ', on the video path' : ''}`
    case 'congestion_cleared': return `${ev.link} back below the threshold (utilization ${ev.utilization})`
    case 'reroute': return `video moved from Path ${ev.from_path} to Path ${ev.to_path}; other path load ${JSON.stringify(ev.other_path_load)}, predicted with video ${ev.predicted_with_video}`
    case 'reroute_confirmed': return `new rules confirmed on all switches in ${ev.install_ms} ms; video on Path ${ev.video_path}`
    case 'reroute_skipped': return `no reroute: ${ev.reason}${ev.link ? ` (${ev.link})` : ''}`
    case 'flows_installed': return `rules installed; video on Path ${ev.video_path}, priority queue ${ev.video_queue ? 'on' : 'off'}${ev.note ? `; ${ev.note}` : ''}`
    default: {
      const { ts, event, received_ts, run_id, mode, demo, ...rest } = ev // eslint-disable-line no-unused-vars
      return Object.entries(rest).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', ')
    }
  }
}

export default function Events() {
  const events = useData('events', { interval: 3000 })
  const [filter, setFilter] = useState('all')
  let body
  if (events.error) body = <ErrorState error={events.error} title="Backend not reachable" hint={<BackendHint />} />
  else if (!events.data) body = <Loading />
  else {
    const rows = [...events.data.events].reverse().filter((e) => filter === 'all' || category(e) === filter)
    body = (
      <Card title={`Controller events (${rows.length})`} subtitle="Newest first. Pushed by the Ryu controller to the backend." source="controller"
        actions={!events.data.controller?.reachable && <span className="text-xs text-critical-ink">controller not reachable: no new events</span>}>
        {rows.length === 0 ? <p className="py-6 text-center text-sm text-ink-3">No events of this type yet.</p> : (
          <div className="max-h-[65vh] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface text-left text-xs text-ink-3">
                <tr><th className="w-6 py-1" /><th className="py-1 pr-3 font-medium">Time</th><th className="py-1 pr-3 font-medium">Event</th><th className="py-1 font-medium">Details</th></tr>
              </thead>
              <tbody>
                {rows.map((e, i) => (
                  <tr key={`${e.ts}-${i}`} className="border-t border-line align-top">
                    <td className="py-1.5">{icon(e)}</td>
                    <td className="py-1.5 pr-3 whitespace-nowrap tabular text-ink-2">{clock(e.ts)}</td>
                    <td className="py-1.5 pr-3 whitespace-nowrap font-mono text-xs text-ink">{e.event}</td>
                    <td className="py-1.5 break-words text-ink-2">{describe(e)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    )
  }
  return (
    <div className="space-y-4">
      <PageHeader title="Event logs">Congestion events, route changes and controller errors, as reported by the controller.</PageHeader>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter events">
        {FILTERS.map((f) => (
          <button key={f.key} type="button" onClick={() => setFilter(f.key)} aria-pressed={filter === f.key}
            className={`rounded-full border px-3 py-1 text-xs ${filter === f.key ? 'border-qos bg-surface font-semibold text-ink' : 'border-line text-ink-2 hover:bg-surface'}`}>
            {f.label}
          </button>
        ))}
      </div>
      {body}
    </div>
  )
}
