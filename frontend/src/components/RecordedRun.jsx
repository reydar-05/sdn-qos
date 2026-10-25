/*
 * Per-second comparison of a recorded baseline run and the matching QoS
 * run (same load, same run number) from the latest experiment.
 * Data: /api/experiments/<id>/runs/<run>/timeseries (saved files only).
 */
import { useMemo, useState } from 'react'
import { TimeChart } from './charts'
import { Card, ErrorState, Loading } from './ui'
import { useData } from '../lib/useData'

const NAME = /^(baseline|qos)-(light|heavy)-run(\d+)$/

function pairs(runDirs) {
  const out = {}
  for (const r of runDirs || []) {
    const m = NAME.exec(r)
    if (!m) continue
    const k = `${m[2]}-run${m[3]}`
    out[k] = { ...(out[k] || {}), [m[1]]: r, load: m[2], run: Number(m[3]) }
  }
  return Object.entries(out).filter(([, v]) => v.baseline && v.qos)
    .sort(([, a], [, b]) => (a.load === b.load ? a.run - b.run : a.load === 'heavy' ? -1 : 1))
}

function merge(base, qos, field) {
  const rows = {}
  for (const [tag, ts] of [['baseline', base], ['qos', qos]]) {
    for (const r of ts?.host || []) {
      rows[r.t] = { ...(rows[r.t] || { t: r.t }), [tag]: r[field] }
    }
  }
  return Object.values(rows).sort((a, b) => a.t - b.t)
}

const MODES = [
  { key: 'baseline', label: 'Baseline (best effort)', color: 'var(--baseline)' },
  { key: 'qos', label: 'QoS (reroute + priority queue)', color: 'var(--qos)' },
]

export default function RecordedRun({ experiment }) {
  const options = useMemo(() => pairs(experiment?.run_dirs), [experiment])
  const [choice, setChoice] = useState(null)
  const sel = options.find(([k]) => k === choice)?.[1] || options[0]?.[1]
  const base = useData('timeseries', { params: { exp: experiment?.id, run: sel?.baseline }, enabled: !!sel })
  const qos = useData('timeseries', { params: { exp: experiment?.id, run: sel?.qos }, enabled: !!sel })

  if (!options.length) {
    return <Card title="Recorded run"><p className="text-sm text-ink-3">This experiment has no baseline and QoS run pair to compare.</p></Card>
  }
  const err = base.error || qos.error
  const ready = base.data && qos.data
  const tl = (qos.data || base.data)?.timeline
  const bands = tl ? [{ x1: tl.bg_start, x2: tl.bg_end, label: 'background traffic' }] : []
  const qosMarks = (qos.data?.events || []).filter((e) => e.event === 'reroute').map((e) => ({ x: e.t, label: 'QoS reroute' }))
  const ctlRows = (ts) => (ts?.controller || []).filter((r) => r.t >= 0)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="run-pick" className="text-sm text-ink-2">Recorded run pair</label>
        <select id="run-pick" value={choice || options[0][0]} onChange={(e) => setChoice(e.target.value)}
          className="rounded border border-line bg-surface px-2 py-1 text-sm text-ink">
          {options.map(([k, v]) => <option key={k} value={k}>{v.load} load, run {v.run}</option>)}
        </select>
        <span className="text-xs text-ink-3">experiment {experiment.id}; {sel.baseline} vs {sel.qos}</span>
      </div>
      {err ? <ErrorState error={err} title="Recorded run unavailable" /> : !ready ? <Loading /> : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <TimeChart title="Video received rate" subtitle="Per second at the client h1 (sent: 4 Mbit/s)" source="host"
            rows={merge(base.data, qos.data, 'video_mbps')} series={MODES} unit="Mbit/s" bands={bands} marks={qosMarks} yDomain={[0, 'auto']} />
          <TimeChart title="Video packet loss" subtitle="Per second, iperf3 receiver report" source="host"
            rows={merge(base.data, qos.data, 'video_loss_pct')} series={MODES} unit="%" bands={bands} marks={qosMarks} yDomain={[0, 'auto']} />
          <TimeChart title="Delay (ping round trip h1 to h2)" subtitle="Per second average; the probe follows the video path and queue" source="host"
            rows={merge(base.data, qos.data, 'ping_ms')} series={MODES} unit="ms" bands={bands} marks={qosMarks} yDomain={[0, 'auto']} />
          <TimeChart title="Video jitter" subtitle="Per second, iperf3 receiver report" source="host"
            rows={merge(base.data, qos.data, 'video_jitter_ms')} series={MODES} unit="ms" digits={3} bands={bands} marks={qosMarks} yDomain={[0, 'auto']} />
          <TimeChart title="Playout buffer level (MODEL)" subtitle="Seconds of video buffered; 0 while background is on means a stall. Model fed by the received bits, not a real player."
            source="model" rows={merge(base.data, qos.data, 'buffer_s')} series={MODES} unit="s" bands={bands} marks={qosMarks} yDomain={[0, 'auto']} />
          <TimeChart title="Background traffic received (h3)" subtitle="Per second; 9 Mbit/s were sent in heavy load" source="host"
            rows={merge(base.data, qos.data, 'bg_mbps')} series={MODES} unit="Mbit/s" bands={bands} yDomain={[0, 'auto']} />
          {[['qos', qos.data], ['baseline', base.data]].map(([tag, ts]) => (
            <TimeChart key={tag} title={`Path utilization, ${tag === 'qos' ? 'QoS' : 'baseline'} run`} subtitle="Server to client direction of each path, per controller poll"
              source="controller" rows={ctlRows(ts)} unit="" digits={3} threshold={0.8} thresholdLabel="threshold 0.8" yDomain={[0, 1.05]} bands={bands}
              marks={tag === 'qos' ? qosMarks : []}
              series={[{ key: 'util_s4->s2', label: 'Path A (s4 to s2)', color: 'var(--path-a)' }, { key: 'util_s4->s3', label: 'Path B (s4 to s3)', color: 'var(--path-b)' }]} />
          ))}
        </div>
      )}
    </div>
  )
}
