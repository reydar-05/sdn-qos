import { Card, ErrorState, Loading, PageHeader, StatusPill } from '../components/ui'
import { TimeChart } from '../components/charts'
import RecordedRun from '../components/RecordedRun'
import { BackendHint, ControllerHint } from '../components/LiveHints'
import { useData } from '../lib/useData'
import { clock, num } from '../lib/format'
import { latestRun } from '../lib/runs'

const PATH_SERIES = [
  { key: 'a', label: 'Path A (s4 to s2)', color: 'var(--path-a)' },
  { key: 'b', label: 'Path B (s4 to s3)', color: 'var(--path-b)' },
]

function LiveCharts({ metrics: all, threshold }) {
  const metrics = latestRun(all)
  const rows = metrics.map((m) => ({
    ts: m.ts,
    a: m.links['s4->s2']?.mbps, b: m.links['s4->s3']?.mbps,
    ua: m.links['s4->s2']?.utilization, ub: m.links['s4->s3']?.utilization,
    v2: m.video_mbps_by_switch?.s2, v3: m.video_mbps_by_switch?.s3,
  }))
  const marks = []
  for (let i = 1; i < metrics.length; i++) {
    if (metrics[i].video_path !== metrics[i - 1].video_path) marks.push({ x: metrics[i].ts, label: `to Path ${metrics[i].video_path}` })
  }
  const common = { xKey: 'ts', xLabel: 'time', xFormat: clock, marks }
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <TimeChart {...common} title="Link throughput" subtitle="Server to client direction, all traffic" source="controller"
        rows={rows} series={PATH_SERIES} unit="Mbit/s" yDomain={[0, 'auto']} />
      <TimeChart {...common} title="Link utilization" subtitle="Throughput / capacity" source="controller"
        rows={rows.map((r) => ({ ts: r.ts, a: r.ua, b: r.ub }))} series={PATH_SERIES} digits={3}
        threshold={threshold} thresholdLabel={`threshold ${threshold}`} yDomain={[0, 1.05]} />
      <TimeChart {...common} title="Video flow rate per path" subtitle="Flow statistics of the video rules on s2 and s3" source="controller"
        rows={rows.map((r) => ({ ts: r.ts, a: r.v2, b: r.v3 }))} unit="Mbit/s" yDomain={[0, 'auto']}
        series={[{ key: 'a', label: 'via s2 (Path A)', color: 'var(--path-a)' }, { key: 'b', label: 'via s3 (Path B)', color: 'var(--path-b)' }]} />
    </div>
  )
}

/** Live end-host samples pushed by the lab (iperf3 receivers and ping), one per second. */
function HostLive({ host }) {
  if (host.error) return <ErrorState error={host.error} />
  if (!host.data) return <Loading />
  const samples = latestRun(host.data.samples)
  if (!host.data.reporter?.reachable || !samples.length) {
    return (
      <Card title="Live end-host measurements" source="host">
        <p className="text-sm text-ink-2">{host.data.reporter?.reason || 'No live end-host samples.'}</p>
        <p className="mt-1 text-xs text-ink-3">They appear while the lab runs (<code className="font-mono">bash scripts/start_lab.sh</code>) and traffic is switched on from its menu.</p>
      </Card>
    )
  }
  const rows = samples.map((s) => ({
    ts: s.ts, v: s.video?.mbps, loss: s.video?.loss_pct, jit: s.video?.jitter_ms, ping: s.ping?.avg_ms,
    bg: s.background?.mbps, bgloss: s.background?.loss_pct,
  }))
  const last = samples.at(-1).traffic || {}
  const common = { xKey: 'ts', xLabel: 'time', xFormat: clock, yDomain: [0, 'auto'] }
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-2">
        Traffic now: video <strong className="text-ink">{last.video ? `ON (${last.video_mbps} Mbit/s)` : 'off'}</strong>,
        background <strong className="text-ink">{last.background === 'off' || !last.background ? 'off' : `${last.background} (${last.background_mbps} Mbit/s)`}</strong>.
        Run {samples.at(-1).run_id}.
      </p>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TimeChart {...common} title="Received rate" subtitle="iperf3 receivers on h1 (video) and h3 (background)" source="host" rows={rows} unit="Mbit/s"
          series={[{ key: 'v', label: 'Video (h1)', color: 'var(--video)' }, { key: 'bg', label: 'Background (h3)', color: 'var(--bg-traffic)' }]} />
        <TimeChart {...common} title="Packet loss" subtitle="Per second, iperf3 receiver report" source="host" rows={rows} unit="%" digits={1}
          series={[{ key: 'loss', label: 'Video', color: 'var(--video)' }, { key: 'bgloss', label: 'Background', color: 'var(--bg-traffic)' }]} />
        <TimeChart {...common} title="Delay (ping h1 to h2)" subtitle="Round trip, average per second; follows the video path" source="host" rows={rows} unit="ms" digits={3}
          series={[{ key: 'ping', label: 'Ping RTT', color: 'var(--video)' }]} />
        <TimeChart {...common} title="Video jitter" subtitle="iperf3 receiver on h1" source="host" rows={rows} unit="ms" digits={3}
          series={[{ key: 'jit', label: 'Video jitter', color: 'var(--video)' }]} />
      </div>
    </div>
  )
}

function QueueTable({ queues }) {
  const q = queues.data
  const ports = [['s4-eth2', 'Path A, s4 to s2'], ['s4-eth3', 'Path B, s4 to s3']]
  return (
    <Card title="Queue status (egress of s4)" source="controller"
      subtitle={`linux-htb on every switch link: max ${q.capacity_mbps} Mbit/s, ${q.queue_limit_packets} packet queues`}>
      <div className="mb-2">{q.enabled === false ? <StatusPill state="off" label="queues disabled in this run (baseline)" />
        : q.enabled ? <StatusPill state="good" label="video queue in use" /> : <StatusPill state="off" label="queue use unknown" />}</div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-sm">
          <thead className="text-left text-xs text-ink-3">
            <tr><th className="py-1 font-medium">Queue</th><th className="py-1 font-medium">Min rate</th>
              {ports.map(([p, l]) => <th key={p} className="py-1 text-right font-medium">{l}</th>)}</tr>
          </thead>
          <tbody>
            {[[q.config.video_queue_id, 'video', q.config.video_min_mbps], [q.config.default_queue_id, 'default', q.config.default_min_mbps]].map(([id, role, min]) => (
              <tr key={id} className="border-t border-line">
                <td className="py-1.5 text-ink">q{id} {role}</td>
                <td className="py-1.5 tabular text-ink-2">{min} Mbit/s</td>
                {ports.map(([p]) => <td key={p} className="py-1.5 text-right tabular text-ink">{q.live ? `${num(q.live[`${p}:q${id}`]?.mbps)} Mbit/s` : 'no live data'}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-ink-3">Rates come from OpenFlow queue statistics. Drop counts per queue are read from the kernel (tc) at the end of each experiment run, see Experiments.</p>
    </Card>
  )
}

export default function Monitoring() {
  const status = useData('status', { interval: 3000 })
  const metrics = useData('metrics', { interval: 2000 })
  const queues = useData('queues', { interval: 2000 })
  const flows = useData('flows', { interval: 4000 })
  const settings = useData('settings')
  const experiment = useData('experiment')
  const host = useData('host', { interval: 2000 })
  const threshold = settings.data?.monitoring?.utilization_threshold ?? 0.8
  const reachable = status.data?.controller?.reachable

  let live
  if (status.error) live = <ErrorState error={status.error} title="Backend not reachable" hint={<BackendHint />} />
  else if (!status.data) live = <Loading />
  else if (!reachable) live = <ErrorState error={{ message: status.data.controller.reason }} title="No live data from the controller" hint={<ControllerHint />} />
  else if (metrics.error) live = <ErrorState error={metrics.error} />
  else if (!metrics.data) live = <Loading />
  else live = <LiveCharts metrics={metrics.data.metrics} threshold={threshold} />

  return (
    <div className="space-y-6">
      <PageHeader title="QoS monitoring and traffic management">
        The controller measures throughput and utilization from port statistics. Delay, jitter and loss can only be
        measured on the end hosts: live from the lab's iperf3 receivers and ping, and per second from recorded experiment runs.
      </PageHeader>

      <section className="space-y-4">
        <h2 className="text-base font-semibold text-ink">Live: controller measurements</h2>
        {live}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card title="Flow classification and current path" source="controller">
            {flows.error ? <ErrorState error={flows.error} /> : !flows.data ? <Loading /> : (
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-ink-3"><tr><th className="py-1 font-medium">Class</th><th className="py-1 font-medium">Match</th><th className="py-1 font-medium">Queue</th><th className="py-1 font-medium">Path now</th></tr></thead>
                <tbody>
                  <tr className="border-t border-line align-top">
                    <td className="py-1.5 font-medium text-ink">Video</td><td className="py-1.5 text-ink-2">{flows.data.classification.video.match}</td>
                    <td className="py-1.5 text-ink-2">q{flows.data.classification.video.queue}</td>
                    <td className="py-1.5 text-ink">{flows.data.video_path ? `Path ${flows.data.video_path}` : 'unknown'}</td>
                  </tr>
                  <tr className="border-t border-line align-top">
                    <td className="py-1.5 font-medium text-ink">Other</td><td className="py-1.5 text-ink-2">{flows.data.classification.other.match}</td>
                    <td className="py-1.5 text-ink-2">q{flows.data.classification.other.queue}</td>
                    <td className="py-1.5 text-ink">Path {flows.data.default_path}</td>
                  </tr>
                </tbody>
              </table>
            )}
          </Card>
          {queues.error ? <ErrorState error={queues.error} /> : !queues.data ? <Loading /> : <QueueTable queues={queues} />}
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-base font-semibold text-ink">Live: end-host measurements</h2>
        {status.error ? <ErrorState error={status.error} title="Backend not reachable" hint={<BackendHint />} /> : <HostLive host={host} />}
      </section>

      <section className="space-y-4">
        <div>
          <h2 className="text-base font-semibold text-ink">Recorded: host measurements, baseline vs QoS</h2>
          <p className="text-sm text-ink-2">Same load and run number, one second per point. The grey band is the background traffic period; the vertical line marks the QoS reroute.</p>
        </div>
        {experiment.error ? <ErrorState error={experiment.error} title="No recorded experiment available" hint={<div>Run <code className="font-mono">scripts/run_experiments.sh</code> to record one.</div>} />
          : !experiment.data ? <Loading /> : <RecordedRun experiment={experiment.data} />}
      </section>
    </div>
  )
}
