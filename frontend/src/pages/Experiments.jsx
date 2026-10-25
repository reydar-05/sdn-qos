import { CheckCircle2, XCircle } from 'lucide-react'
import { Card, ErrorState, KeyValue, Loading, PageHeader, SourceTag, StatusPill } from '../components/ui'
import { GroupBars } from '../components/charts'
import { BackendHint } from '../components/LiveHints'
import { useData } from '../lib/useData'
import { dateTime, num, range } from '../lib/format'

const LOADS = ['light', 'heavy']
const MODES = [
  { key: 'baseline', label: 'Baseline', color: 'var(--baseline)' },
  { key: 'qos', label: 'QoS', color: 'var(--qos)' },
]

// metric key, label, unit, source, digits
const HOST_METRICS = [
  ['steady_video_mbps', 'Video received rate', 'Mbit/s', 'host', 2],
  ['steady_video_loss_pct', 'Video packet loss', '%', 'host', 1],
  ['steady_video_jitter_ms', 'Video jitter', 'ms', 'host', 3],
  ['steady_ping_avg_ms', 'Ping delay (average)', 'ms', 'host', 2],
  ['steady_ping_lost', 'Ping probes lost', 'probes', 'host', 0],
  ['steady_bg_mbps', 'Background received rate', 'Mbit/s', 'host', 2],
  ['steady_bg_loss_pct', 'Background loss', '%', 'host', 1],
  ['load_bg_loss_pct', 'Background loss, whole load period', '%', 'host', 1],
  ['model_stall_count', 'Stalls (playout MODEL)', 'stalls', 'model', 1],
  ['model_stall_time_s', 'Stall time (playout MODEL)', 's', 'model', 2],
]
const CTL_METRICS = [
  ['ctl_congestion_detected_s', 'Congestion detected after load start', 's', 'controller', 2],
  ['ctl_reroute_s', 'Reroute after load start', 's', 'controller', 2],
  ['ctl_reroute_install_ms', 'Reroute rule install time', 'ms', 'controller', 1],
  ['ctl_reroutes', 'Reroutes per run', '', 'controller', 0],
  ['ctl_util_steady_s4->s2', 'Utilization Path A (s4 to s2)', '', 'controller', 3],
  ['ctl_util_steady_s4->s3', 'Utilization Path B (s4 to s3)', '', 'controller', 3],
  ['tc_s4-eth2:q0_dropped', 'Drops, s4 to s2 default queue', 'packets', 'tc', 0],
  ['tc_s4-eth2:q1_dropped', 'Drops, s4 to s2 video queue', 'packets', 'tc', 0],
  ['tc_s4-eth3:q0_dropped', 'Drops, s4 to s3 default queue', 'packets', 'tc', 0],
  ['tc_s4-eth3:q1_dropped', 'Drops, s4 to s3 video queue', 'packets', 'tc', 0],
]
const CHARTS = ['steady_video_loss_pct', 'steady_ping_avg_ms', 'steady_video_jitter_ms', 'steady_video_mbps', 'model_stall_count', 'steady_bg_loss_pct']

function groupMap(summary) {
  const g = {}
  for (const x of summary?.groups || []) g[`${x.mode}-${x.load}`] = x
  return g
}

function EnvironmentCard() {
  const env = useData('environment')
  return (
    <Card title="Environment checks" subtitle="Latest verification run per phase (results/verify)" source="verify">
      {env.error ? <ErrorState error={env.error} /> : !env.data ? <Loading /> : !env.data.latest.length
        ? <p className="text-sm text-ink-3">No verification logs found.</p> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-3"><tr><th className="py-1 font-medium">Check</th><th className="py-1 font-medium">Result</th><th className="py-1 font-medium">Log</th></tr></thead>
            <tbody>
              {env.data.latest.map((c) => (
                <tr key={c.name} className="border-t border-line">
                  <td className="py-1.5 font-medium text-ink">{c.phase}</td>
                  <td className="py-1.5">{c.failed === 0 && c.passed > 0
                    ? <span className="inline-flex items-center gap-1 text-good-ink"><CheckCircle2 className="h-4 w-4" aria-hidden />{c.passed} passed</span>
                    : <span className="inline-flex items-center gap-1 text-critical-ink"><XCircle className="h-4 w-4" aria-hidden />{c.passed} passed, {c.failed} failed</span>}</td>
                  <td className="py-1.5 break-all font-mono text-xs text-ink-3">{c.file}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </Card>
  )
}

function MetricTable({ title, metrics, groups }) {
  const cols = LOADS.flatMap((l) => MODES.map((m) => [`${m.key}-${l}`, `${m.label}, ${l}`]))
  return (
    <Card title={title} subtitle="Mean over the valid runs, with the range (min to max) when runs differ">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="text-left text-xs text-ink-3">
            <tr><th className="py-1 font-medium">Metric</th><th className="py-1 font-medium">Source</th>
              {cols.map(([k, l]) => <th key={k} className="py-1 text-right font-medium">{l}</th>)}</tr>
          </thead>
          <tbody>
            {metrics.map(([key, label, unit, source, digits]) => (
              <tr key={key} className="border-t border-line align-top">
                <td className="py-1.5 text-ink">{label}{unit ? <span className="text-ink-3"> ({unit})</span> : null}</td>
                <td className="py-1.5"><SourceTag source={source} /></td>
                {cols.map(([k]) => <td key={k} className="py-1.5 text-right tabular text-ink">{range(groups[k]?.metrics?.[key], digits)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function Limitations({ groups }) {
  const qh = groups['qos-heavy']?.metrics || {}
  const bl = groups['baseline-light']?.metrics || {}
  const ql = groups['qos-light']?.metrics || {}
  return (
    <Card title="Limitations and how to read these results">
      <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
        <li>Emulated network: Mininet on one VM, links shaped by Open vSwitch linux-htb queues (10 Mbit/s). All hosts share one kernel, so the absolute numbers are not those of real hardware.</li>
        <li>The video is an iperf3 UDP stream at a constant 4 Mbit/s on port 5004, not a real encoded video. There is no picture quality score (no MOS, SSIM or VMAF).</li>
        <li>Stalls and stall time come from a playout buffer MODEL fed by the received bits per second. They are an estimate of buffering, not a measurement from a real player.</li>
        <li>Delay is the ping round trip time between h1 and h2; the probe follows the video path and queue. Jitter and loss come from the iperf3 receiver. The controller does not measure delay, jitter or loss.</li>
        <li>Under light load ({num(bl.steady_video_mbps?.mean)} Mbit/s video plus 3 Mbit/s background, below the threshold) there was nothing to fix: no reroute happened and both modes delivered all the video. The small ping difference ({num(bl.steady_ping_avg_ms?.mean, 3)} vs {num(ql.steady_ping_avg_ms?.mean, 3)} ms) is well below a millisecond and should not be read as a QoS gain.</li>
        <li>The controller needs several polls to act: congestion was detected about {num(qh.ctl_congestion_detected_s?.mean, 1)} s after the load started (3 polls over threshold at a 2 s interval). Before the reroute the background flow still lost packets, which is why its loss over the whole load period ({num(qh.load_bg_loss_pct?.mean, 1)}%) is above zero in QoS mode.</li>
        <li>The QoS result depends on a free alternative path. With both paths full, rerouting would not help and only the priority queue would protect the video.</li>
        <li>Each case was run {groups['qos-heavy']?.runs ?? '?'} times. That is enough to see a consistent difference here, not to give tight statistical confidence intervals.</li>
      </ul>
    </Card>
  )
}

export default function Experiments() {
  const exp = useData('experiment')
  if (exp.error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Experiments and results" />
        <ErrorState error={exp.error} title="No experiment results available"
          hint={exp.error.kind === 'http' ? <div>Record one with <code className="font-mono">scripts/run_experiments.sh</code>.</div> : <BackendHint />} />
        <EnvironmentCard />
      </div>
    )
  }
  if (!exp.data) return <Loading />
  const e = exp.data
  const groups = groupMap(e.summary)
  const meta = e.meta || {}
  const nRuns = (e.summary?.groups || []).reduce((a, g) => a + g.runs, 0)
  const nValid = (e.summary?.groups || []).reduce((a, g) => a + g.valid_runs, 0)
  const chartRows = (key) => LOADS.map((l) => ({ load: l, baseline: groups[`baseline-${l}`]?.metrics?.[key]?.mean, qos: groups[`qos-${l}`]?.metrics?.[key]?.mean }))
  const all = Object.fromEntries([...HOST_METRICS, ...CTL_METRICS].map((m) => [m[0], m]))

  return (
    <div className="space-y-4">
      <PageHeader title="Experiments and results">
        Best-effort baseline against the QoS controller (congestion detection, reroute, priority queue), under light and heavy
        background load. {e.demo
          ? 'In DEMO MODE the numbers below are invented sample values that only show the layout; they are not measured.'
          : "Numbers below are read from the experiment's result files, measured in the steady window"}
        {!e.demo && ` (${meta.timeline?.windows?.steady?.join(' to ')} s of each ${meta.timeline?.duration} s run).`}
      </PageHeader>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="This experiment">
          <KeyValue rows={[
            ['Experiment id', e.id],
            ['Started', meta.started ? dateTime(meta.started) : meta.started_local || 'n/a'],
            ['Runs (valid)', `${nRuns} (${nValid})`],
            ['Duration per run', `${meta.timeline?.duration ?? '?'} s, background ${meta.timeline?.bg_start ?? '?'} to ${meta.timeline?.bg_end ?? '?'} s`],
            ...Object.entries(meta.versions || {}).map(([k, v]) => [k, v]),
          ]} />
          <div className="mt-3">{nValid === nRuns && nRuns > 0 ? <StatusPill state="good" label="all runs passed the validity check (senders sent at least 97% of the asked rate)" />
            : <StatusPill state="warn" label={`${nRuns - nValid} run(s) invalid and left out of the means`} />}</div>
          {e.summary?.note && <p className="mt-2 text-xs text-ink-3">{e.summary.note}</p>}
        </Card>
        <EnvironmentCard />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {CHARTS.map((key) => {
          const [, label, unit, source, digits] = all[key]
          return <GroupBars key={key} title={label} subtitle={`Mean of the valid runs, steady window${unit ? `, ${unit}` : ''}`} source={source}
            rows={chartRows(key)} xKey="load" series={MODES} unit={unit} digits={digits} />
        })}
      </div>

      <MetricTable title="Host measurements and model" metrics={HOST_METRICS} groups={groups} />
      <MetricTable title="Controller reaction and queue drops" metrics={CTL_METRICS} groups={groups} />
      <Limitations groups={groups} />
      {e.runs?.length > 0 && (
        <Card title="Individual runs" subtitle={`runs.csv, ${e.runs.length} rows`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-xs tabular">
              <thead className="text-left text-ink-3"><tr>
                {['run', 'valid', 'video Mbit/s', 'video loss %', 'ping ms', 'stalls (model)', 'reroutes', 'detected s'].map((h) => <th key={h} className="py-1 pr-2 font-medium">{h}</th>)}
              </tr></thead>
              <tbody>
                {e.runs.map((r) => (
                  <tr key={r.name} className="border-t border-line">
                    <td className="py-1 pr-2 font-mono text-ink">{r.name}</td>
                    <td className="py-1 pr-2 text-ink-2">{r.valid === 'True' ? 'yes' : `no: ${r.problems}`}</td>
                    <td className="py-1 pr-2 text-ink">{num(Number(r.steady_video_mbps))}</td>
                    <td className="py-1 pr-2 text-ink">{num(Number(r.steady_video_loss_pct), 1)}</td>
                    <td className="py-1 pr-2 text-ink">{num(Number(r.steady_ping_avg_ms), 3)}</td>
                    <td className="py-1 pr-2 text-ink">{r.model_stall_count}</td>
                    <td className="py-1 pr-2 text-ink">{r.ctl_reroutes}</td>
                    <td className="py-1 pr-2 text-ink">{r.ctl_congestion_detected_s || 'n/a'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
