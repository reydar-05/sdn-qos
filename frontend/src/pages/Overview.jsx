import { Card, ErrorState, KeyValue, Loading, Meter, PageHeader, StatTile, StatusPill } from '../components/ui'
import { BackendHint, ControllerHint } from '../components/LiveHints'
import { useData } from '../lib/useData'
import { num, pct } from '../lib/format'
import { latestRun } from '../lib/runs'

function HostCard({ host }) {
  const samples = latestRun(host.data?.samples).slice(-5)
  const ok = host.data?.reporter?.reachable && samples.length
  const avg = (f) => {
    const xs = samples.map(f).filter((x) => x !== null && x !== undefined)
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null
  }
  return (
    <Card title="End hosts, last 5 s" subtitle="Measured by iperf3 and ping on the hosts, not by the controller" source="host">
      {host.error ? <ErrorState error={host.error} /> : !ok ? (
        <p className="text-sm text-ink-3">{host.data?.reporter?.reason || 'No live end-host samples.'}</p>
      ) : (
        <KeyValue rows={[
          ['Video received', `${num(avg((s) => s.video?.mbps), 2)} Mbit/s`],
          ['Video loss', `${num(avg((s) => s.video?.loss_pct), 1)}%`],
          ['Video jitter', `${num(avg((s) => s.video?.jitter_ms), 3)} ms`],
          ['Ping delay h1 to h2', `${num(avg((s) => s.ping?.avg_ms), 3)} ms`],
          ['Background', samples.at(-1).traffic?.background || 'off'],
        ]} />
      )}
    </Card>
  )
}

const DIRECTIONS = [
  ['s4->s2', 'A'], ['s2->s1', 'A'], ['s1->s2', 'A'], ['s2->s4', 'A'],
  ['s4->s3', 'B'], ['s3->s1', 'B'], ['s1->s3', 'B'], ['s3->s4', 'B'],
]

function LinkTable({ metric, threshold }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] text-sm">
        <thead className="text-left text-xs text-ink-3">
          <tr>
            <th className="py-1 font-medium">Link direction</th>
            <th className="py-1 font-medium">Path</th>
            <th className="py-1 text-right font-medium">Throughput</th>
            <th className="w-2/5 py-1 pl-4 font-medium">Utilization</th>
            <th className="py-1 pl-3 font-medium">State</th>
          </tr>
        </thead>
        <tbody>
          {DIRECTIONS.map(([d, path]) => {
            const l = metric.links[d] || {}
            return (
              <tr key={d} className="border-t border-line">
                <td className="py-1.5 font-mono text-xs text-ink">{d}{l.on_video_path ? ' (video)' : ''}</td>
                <td className="py-1.5 text-ink-2">{path}</td>
                <td className="py-1.5 text-right tabular text-ink">{num(l.mbps, 2)} Mbit/s</td>
                <td className="py-1.5 pl-4">
                  <div className="flex items-center gap-2">
                    <Meter value={l.utilization} threshold={threshold} congested={l.congested} />
                    <span className="w-10 text-right text-xs tabular text-ink-2">{pct(l.utilization)}</span>
                  </div>
                </td>
                <td className="py-1.5 pl-3">
                  {l.stale ? <StatusPill state="off" label="stale" />
                    : l.congested ? <StatusPill state="bad" label="congested" />
                      : <StatusPill state="good" label="ok" />}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ConfigCard({ settings }) {
  if (settings.error) return <ErrorState error={settings.error} title="Settings unavailable" />
  if (!settings.data) return <Loading />
  const s = settings.data
  return (
    <Card title="Configuration (read only)" subtitle={`Edit ${s.config_file} and restart to change`} source="config">
      <KeyValue rows={[
        ['Video port (UDP)', s.video.port],
        ['Video bitrate', `${s.video.bitrate_mbps} Mbit/s`],
        ['Bottleneck capacity', `${s.links.default_capacity_mbps} Mbit/s per link`],
        ['Utilization threshold', pct(s.monitoring.utilization_threshold)],
        ['Consecutive polls to act', s.monitoring.consecutive_polls],
        ['Poll interval', `${s.monitoring.poll_interval_s} s`],
        ['Reroute cooldown', `${s.monitoring.cooldown_s} s`],
        ['Max reroutes per run', s.monitoring.max_reroutes_per_run],
        ['Video queue / min rate', `q${s.queues.video_queue_id}, ${s.queues.video_min_mbps} Mbit/s`],
        ['Default queue / min rate', `q${s.queues.default_queue_id}, ${s.queues.default_min_mbps} Mbit/s`],
        ['Switch queue length', `${s.links.queue_limit_packets} packets`],
        ['OpenFlow port', `${s.ports.openflow} (localhost only)`],
      ]} />
    </Card>
  )
}

export default function Overview() {
  const status = useData('status', { interval: 3000 })
  const metrics = useData('metrics', { interval: 2000 })
  const flows = useData('flows', { interval: 4000 })
  const settings = useData('settings')
  const host = useData('host', { interval: 2000 })
  const threshold = settings.data?.monitoring?.utilization_threshold ?? 0.8

  let live
  if (status.error) live = <ErrorState error={status.error} title="Backend not reachable" hint={<BackendHint />} />
  else if (!status.data) live = <Loading label="Asking the backend for the controller status" />
  else if (!status.data.controller.reachable) {
    live = <ErrorState error={{ message: status.data.controller.reason }} title="No live data from the controller" hint={<ControllerHint />} />
  } else {
    const s = status.data
    const ctl = s.controller
    const m = metrics.data?.metrics?.at(-1)
    const congested = s.congested_links || []
    live = (
      <>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <StatTile label="Controller" value={`${ctl.switches_connected?.length ?? '?'} / 4`} unit="switches"
            note={`mode ${ctl.mode || s.mode}, last data ${num(ctl.last_seen_s_ago, 1)} s ago`}>
            <div className="mt-1"><StatusPill state="good" label="connected" /></div>
          </StatTile>
          <StatTile label="Video path" value={`Path ${s.video_path ?? '?'}`}
            note={s.video_path === 'B' ? 's1 - s3 - s4 (alternative)' : 's1 - s2 - s4 (default)'} />
          <StatTile label="Congestion" value={congested.length ? `${congested.length} link dir.` : 'none'}
            note={congested.length ? congested.join(', ') : `all links below ${pct(threshold)}`}>
            <div className="mt-1">{congested.length ? <StatusPill state="bad" label="congested" /> : <StatusPill state="good" label="normal" />}</div>
          </StatTile>
          <StatTile label="Reroutes this run" value={s.reroutes ?? 0}
            note={ctl.reroute_enabled === false ? 'rerouting is off (baseline)' : 'rerouting enabled'} />
          <StatTile label="Video rate at s1" value={num(m?.video_mbps_by_switch?.s1, 2)} unit="Mbit/s"
            note="controller flow statistics" />
        </div>
        <Card title="Link utilization (latest poll)" subtitle="Each link has two directions. Video goes from h2 (s4) to h1 (s1)." source="controller">
          {m ? <LinkTable metric={m} threshold={threshold} /> : metrics.error ? <ErrorState error={metrics.error} /> : <Loading />}
        </Card>
      </>
    )
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Overview">
        Current state of the SDN controller and the network. The controller polls switch port statistics,
        detects congestion on the video path and moves the video flow to the other path.
      </PageHeader>
      {live}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {!status.error && <HostCard host={host} />}
        <Card title="Active flow classes" source="controller">
          {flows.error ? <ErrorState error={flows.error} /> : !flows.data ? <Loading /> : (
            <div className="space-y-3 text-sm">
              <div className="rounded border border-line p-3">
                <p className="font-medium text-ink">Video (priority queue q{flows.data.classification.video.queue})</p>
                <p className="text-ink-2">{flows.data.classification.video.match}</p>
                <p className="mt-1 text-xs text-ink-3">Current path: {flows.data.video_path ? `Path ${flows.data.video_path}` : 'unknown (no live data)'}.
                  {flows.data.classification.video.ping_probe_follows_video && ' The h1 to h2 ping probe follows the video path.'}</p>
              </div>
              <div className="rounded border border-line p-3">
                <p className="font-medium text-ink">Other traffic (default queue q{flows.data.classification.other.queue})</p>
                <p className="text-ink-2">{flows.data.classification.other.match}, always on Path {flows.data.default_path}</p>
              </div>
            </div>
          )}
        </Card>
        <ConfigCard settings={settings} />
      </div>
    </div>
  )
}
