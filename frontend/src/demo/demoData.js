/*
 * DEMO DATA
 * =========
 * Invented sample values that let the dashboard run with no lab and no
 * backend (for example on Vercel). They are NOT experimental results.
 * The numbers are round, illustrative values with the same shape as the
 * real backend responses, and the sequence is the same on every page load
 * (no randomness), so a demo is repeatable.
 *
 * Every object returned from this file carries demo: true, and the
 * dashboard shows a "DEMO DATA" stamp on every page and chart that uses it.
 * Real results only ever come from the Flask backend in LIVE LAB mode.
 */

export const DEMO_FILE = 'frontend/src/demo/demoData.js'

const POLL_S = 2
const CYCLE = 60 // polls in one demo scenario (2 minutes)
const CAPACITY = 10
const VIDEO = 4

const DIRS = ['s1->s2', 's2->s1', 's2->s4', 's4->s2', 's1->s3', 's3->s1', 's3->s4', 's4->s3']
const PATH_A = ['s4->s2', 's2->s1']
const PATH_B = ['s4->s3', 's3->s1']

// Small fixed wobble so lines do not look perfectly flat (deterministic).
const wobble = (i, amp) => Math.round(Math.sin(i * 1.7) * amp * 1000) / 1000

/*
 * Scenario, one cycle of 60 polls:
 *   polls 0-4   video only on Path A
 *   polls 5-34  9 Mbit/s background traffic joins Path A
 *   poll  7     third poll over the 0.8 threshold: congestion detected, video moved to Path B
 *   polls 35-59 background stops, congestion clears after 3 polls, video stays on Path B
 */
function pollState(p) {
  const bgOn = p >= 5 && p <= 34
  const rerouted = p >= 7
  const path = rerouted ? 'B' : 'A'
  const linkMbps = {}
  for (const d of DIRS) linkMbps[d] = 0.007
  const add = (dirs, mbps) => dirs.forEach((d) => { linkMbps[d] = Math.min(CAPACITY, linkMbps[d] + mbps) })
  add(path === 'A' ? PATH_A : PATH_B, VIDEO + 0.12 + wobble(p, 0.02))
  if (bgOn) add(PATH_A, 9 + 0.27 + wobble(p + 3, 0.03))
  // consecutive polls over threshold, worked out from the scenario timeline
  const aOver = bgOn ? Math.min(3, p - 4) : (p >= 35 && p <= 37 ? 3 - (p - 34) : 0)
  const aCongested = (bgOn && p - 4 >= 3) || (p >= 35 && p < 37)
  return { bgOn, path, linkMbps, aOver, aCongested }
}

function metricRecord(p, ts) {
  const s = pollState(p)
  const links = {}
  for (const d of DIRS) {
    const onA = PATH_A.includes(d)
    const mbps = Math.round(s.linkMbps[d] * 1000) / 1000
    links[d] = {
      mbps,
      utilization: Math.round((mbps / CAPACITY) * 10000) / 10000,
      tx_dropped_per_s: onA && s.bgOn ? Math.round(110 + wobble(p, 8)) : 0,
      capacity_mbps: CAPACITY,
      over_count: onA ? Math.max(0, s.aOver) : 0,
      congested: onA && s.aCongested,
      stale: false,
      on_video_path: (s.path === 'A' ? PATH_A : PATH_B).includes(d),
    }
  }
  const vb = Math.round((VIDEO + 0.12 + wobble(p, 0.02)) * 1000) / 1000
  return {
    demo: true,
    ts,
    poll: p + 1,
    mode: 'qos',
    video_path: s.path,
    links,
    video_mbps_by_switch: { s1: vb, s4: vb, s2: s.path === 'A' ? vb : 0, s3: s.path === 'B' ? vb : 0 },
    congested_links: s.aCongested ? [...PATH_A] : [],
    queues: {
      's4-eth2:q1': { mbps: s.path === 'A' ? vb : 0 },
      's4-eth2:q0': { mbps: s.bgOn ? (s.path === 'A' ? 5.9 : 9.27) : 0.007 },
      's4-eth3:q1': { mbps: s.path === 'B' ? vb : 0 },
      's4-eth3:q0': { mbps: 0.007 },
    },
    reroutes: s.path === 'B' ? 1 : 0,
  }
}

// The demo clock starts 20 polls before the page loads, so the first view
// already has history: the reroute has happened and Path A is congested.
const PREFILL_POLLS = 20
const START = Date.now() / 1000 - PREFILL_POLLS * POLL_S

/** Index of the current demo poll (grows by one every 2 s). */
export function demoTick(now = Date.now() / 1000) {
  return Math.floor((now - START) / POLL_S)
}

function eventsUpTo(tick) {
  const out = []
  for (let i = 0; i <= tick; i++) {
    const p = i % CYCLE
    const ts = START + i * POLL_S
    const e = (ev) => out.push({ demo: true, ts, ...ev })
    if (p === 0) e({ event: 'flows_installed', mode: 'qos', video_path: 'A', default_path: 'A', video_queue: true, note: 'demo scenario (re)starts' })
    if (p === 7) {
      e({ event: 'congestion_detected', link: 's4->s2', utilization: 1.0, threshold: 0.8, polls: 3, on_video_path: true, video_path: 'A' })
      e({ event: 'reroute', reroute_no: 1, from_path: 'A', to_path: 'B', trigger_links: ['s4->s2'], other_path_load: { B: 0.0 }, predicted_with_video: 0.41, video_rate_mbps: 4.1, video_queue: true })
      e({ event: 'reroute_confirmed', video_path: 'B', install_ms: 10.0 })
    }
    if (p === 22) e({ event: 'reroute_skipped', reason: 'cooldown', link: 's4->s2' })
    if (p === 37) e({ event: 'congestion_cleared', link: 's4->s2', utilization: 0.0, threshold: 0.8, polls: 3, on_video_path: false, video_path: 'B' })
    if (p === 48) e({ event: 'stats_missing', switch: 's3', note: 'example of a skipped poll' })
  }
  return out
}

// Per-second end-host samples (same shape as /api/host). QoS demo: the video
// stays clean, the background loses packets until the reroute.
function hostSample(i) {
  const p = Math.floor(i / 2) % CYCLE
  const s = pollState(p)
  const beforeReroute = s.bgOn && p < 7
  return {
    demo: true,
    ts: START + i,
    run_id: 'demo',
    video: { mbps: Math.round((4 + wobble(i, 0.04)) * 1000) / 1000, loss_pct: 0, jitter_ms: beforeReroute ? 0.2 : 0.08 + Math.abs(wobble(i, 0.02)) },
    background: s.bgOn ? { mbps: beforeReroute ? 6.0 : 9.0, loss_pct: beforeReroute ? 33 : 0, jitter_ms: 0.1 } : null,
    ping: { avg_ms: beforeReroute ? 2 + Math.abs(wobble(i, 0.5)) : 0.12 + Math.abs(wobble(i, 0.03)), lost: 0, replies: 5 },
    traffic: { video: true, video_mbps: 4, background: s.bgOn ? 'heavy' : 'off', background_mbps: s.bgOn ? 9 : 0 },
  }
}

export function demoHost(limit = 120) {
  const now = Math.floor(Date.now() / 1000 - START)
  const rows = []
  for (let i = Math.max(0, now - limit + 1); i <= now; i++) rows.push(hostSample(i))
  return { demo: true, reporter: { reachable: true, last_seen_s_ago: 0.5 }, source: 'DEMO DATA (no hosts)', samples: rows }
}

// ---------------------------------------------------------------------------
// Responses with the same shape as the Flask endpoints
// ---------------------------------------------------------------------------
const controllerOk = () => ({
  demo: true, reachable: true, last_seen_s_ago: 0.4, stale_after_s: 8, mode: 'qos', run_id: 'demo',
  switches_connected: ['s1', 's2', 's3', 's4'], flows_installed: true, reroute_enabled: true, queues_enabled: true,
})

export function demoStatus() {
  const t = demoTick()
  const m = metricRecord(t % CYCLE, START + t * POLL_S)
  return { demo: true, controller: controllerOk(), live: true, latest_metrics_ts: m.ts, video_path: m.video_path,
    congested_links: m.congested_links, reroutes: m.reroutes, mode: 'qos' }
}

export function demoMetrics(limit = 150) {
  const t = demoTick()
  const rows = []
  for (let i = Math.max(0, t - limit + 1); i <= t; i++) rows.push(metricRecord(i % CYCLE, START + i * POLL_S))
  return { demo: true, controller: controllerOk(), metrics: rows.map((r) => ({ ...r, run_id: 'demo' })) }
}

export function demoEvents() {
  return { demo: true, controller: controllerOk(), events: eventsUpTo(demoTick()).slice(-500) }
}

export const demoSettings = {
  demo: true,
  video: { port: 5004, bitrate_mbps: 4, server: 'h2', client: 'h1', ping_follows_video: true },
  monitoring: { poll_interval_s: 2, utilization_threshold: 0.8, consecutive_polls: 3, cooldown_s: 20, max_reroutes_per_run: 4, stats_timeout_s: 5 },
  links: { default_capacity_mbps: 10, queue_limit_packets: 25 },
  queues: { video_queue_id: 1, default_queue_id: 0, video_min_mbps: 6, default_min_mbps: 4 },
  background: { host: 'h3', port: 5201, light_mbps: 3, heavy_mbps: 9 },
  experiment: { duration_s: 60, background_start_s: 10, background_stop_before_end_s: 10, settle_s: 10, runs: 3 },
  playout_model: { startup_buffer_s: 2.0, resume_buffer_s: 1.0 },
  ports: { openflow: 6653, backend: 5000 },
  config_file: 'config/config.yaml',
}

const TOPO_LINKS = [
  { a: 's1', a_port: 3, b: 's2', b_port: 1 },
  { a: 's2', a_port: 2, b: 's4', b_port: 2 },
  { a: 's1', a_port: 4, b: 's3', b_port: 1 },
  { a: 's3', a_port: 2, b: 's4', b_port: 3 },
]

export function demoTopology() {
  const t = demoTick()
  const m = metricRecord(t % CYCLE, START + t * POLL_S)
  return {
    demo: true, controller: controllerOk(),
    switches: { s1: 1, s2: 2, s3: 3, s4: 4 },
    hosts: {
      h1: { ip: '10.0.0.1', mac: '00:00:00:00:00:01', switch: 's1', port: 1, role: 'client' },
      h2: { ip: '10.0.0.2', mac: '00:00:00:00:00:02', switch: 's4', port: 1, role: 'server' },
      h3: { ip: '10.0.0.3', mac: '00:00:00:00:00:03', switch: 's1', port: 2, role: 'background' },
    },
    links: TOPO_LINKS.map((l) => ({ ...l, capacity_mbps: CAPACITY,
      directions: { [`${l.a}->${l.b}`]: m.links[`${l.a}->${l.b}`], [`${l.b}->${l.a}`]: m.links[`${l.b}->${l.a}`] } })),
    paths: { A: ['s1', 's2', 's4'], B: ['s1', 's3', 's4'] },
    primary_path: 'A', video_path: m.video_path, congested_links: m.congested_links,
  }
}

export function demoFlows() {
  const t = demoTick()
  const m = metricRecord(t % CYCLE, START + t * POLL_S)
  return {
    demo: true, controller: controllerOk(), paths: { A: ['s1', 's2', 's4'], B: ['s1', 's3', 's4'] }, default_path: 'A',
    video_path: m.video_path,
    classification: {
      video: { match: 'UDP port 5004 (source or destination), h2 <-> h1', queue: 1, ping_probe_follows_video: true },
      other: { match: 'IPv4 by destination address', queue: 0 },
    },
    video_mbps_by_switch: m.video_mbps_by_switch, mode: 'qos',
  }
}

export function demoQueues() {
  const t = demoTick()
  const m = metricRecord(t % CYCLE, START + t * POLL_S)
  return { demo: true, controller: controllerOk(), config: demoSettings.queues, capacity_mbps: CAPACITY,
    queue_limit_packets: 25, enabled: true, live: m.queues }
}

export const demoEnvironment = {
  demo: true,
  latest: [
    { name: 'phase1-demo', phase: 'phase1', passed: 11, failed: 0, file: 'results/verify/phase1-demo.log' },
    { name: 'phase2-demo', phase: 'phase2', passed: 12, failed: 0, file: 'results/verify/phase2-demo.log' },
    { name: 'phase3-demo', phase: 'phase3', passed: 29, failed: 0, file: 'results/verify/phase3-demo.log' },
  ],
}

// --- experiment summary (same shape as results/experiments/<id>/summary.json) ---
const stat = (mean, min = mean, max = mean) => ({ mean, min, max, n: 3 })
const group = (mode, load, m) => ({ mode, load, runs: 3, valid_runs: 3, invalid: [], metrics: m })

export const demoExperiment = {
  demo: true,
  id: 'demo-experiment',
  meta: {
    started_local: 'demo', args: { mode: 'both', load: 'both', duration_s: 60, runs: 3 },
    timeline: { duration: 60, bg_start: 10, bg_end: 50, windows: { pre: [0, 10], load: [10, 50], steady: [20, 50], post: [50, 60] } },
    versions: { note: 'demo data, no lab versions' },
  },
  summary: {
    id: 'demo-experiment',
    note: 'DEMO DATA: invented illustrative numbers, not measured.',
    windows_explained: { steady: 'from settle_s after background start to background end', load: 'whole background period' },
    groups: [
      group('baseline', 'light', { steady_video_mbps: stat(4.0), steady_video_loss_pct: stat(0), steady_video_jitter_ms: stat(0.1), steady_ping_avg_ms: stat(0.2), steady_ping_lost: stat(0), steady_bg_mbps: stat(3), steady_bg_loss_pct: stat(0), model_stall_count: stat(0), model_stall_time_s: stat(0), ctl_reroutes: stat(0), 'ctl_util_steady_s4->s2': stat(0.7), 'ctl_util_steady_s4->s3': stat(0) }),
      group('qos', 'light', { steady_video_mbps: stat(4.0), steady_video_loss_pct: stat(0), steady_video_jitter_ms: stat(0.1), steady_ping_avg_ms: stat(0.1), steady_ping_lost: stat(0), steady_bg_mbps: stat(3), steady_bg_loss_pct: stat(0), model_stall_count: stat(0), model_stall_time_s: stat(0), ctl_reroutes: stat(0), 'ctl_util_steady_s4->s2': stat(0.7), 'ctl_util_steady_s4->s3': stat(0) }),
      group('baseline', 'heavy', { steady_video_mbps: stat(2.5, 2.0, 3.0), steady_video_loss_pct: stat(30, 20, 40), steady_video_jitter_ms: stat(0.5, 0.4, 0.6), steady_ping_avg_ms: stat(30, 29, 31), steady_ping_lost: stat(50, 45, 55), steady_bg_mbps: stat(7, 6.5, 7.5), steady_bg_loss_pct: stat(20, 15, 25), load_bg_loss_pct: stat(20, 15, 25), model_stall_count: stat(6, 4, 8), model_stall_time_s: stat(7, 5, 9), ctl_congestion_detected_s: stat(6), ctl_reroutes: stat(0), 'ctl_util_steady_s4->s2': stat(1.0), 'ctl_util_steady_s4->s3': stat(0), 'tc_s4-eth2:q0_dropped': stat(10000, 9000, 11000) }),
      group('qos', 'heavy', { steady_video_mbps: stat(4.0), steady_video_loss_pct: stat(0), steady_video_jitter_ms: stat(0.1), steady_ping_avg_ms: stat(0.1), steady_ping_lost: stat(0), steady_bg_mbps: stat(9), steady_bg_loss_pct: stat(0), load_bg_loss_pct: stat(5), model_stall_count: stat(0), model_stall_time_s: stat(0), ctl_congestion_detected_s: stat(6), ctl_reroute_s: stat(6), ctl_reroute_install_ms: stat(10, 8, 12), ctl_reroutes: stat(1), 'ctl_util_steady_s4->s2': stat(0.9), 'ctl_util_steady_s4->s3': stat(0.4), 'tc_s4-eth2:q0_dropped': stat(1500, 1400, 1600) }),
    ],
  },
  runs: [],
  run_dirs: ['baseline-heavy-run1', 'qos-heavy-run1'],
}

// --- per-second recorded run (same shape as /api/experiments/<id>/runs/<run>/timeseries) ---
function playout(bitsPerSec, bitrate, startup = 2, resume = 1) {
  // same rules as sdn/playout_model.py
  let buf = 0, playing = false, started = false
  return bitsPerSec.map((bits) => {
    buf += bits / bitrate
    if (!playing) {
      if (buf >= (started ? resume : startup) - 1e-3) { playing = true; started = true }
    } else if (buf >= 1) buf -= 1
    else { buf = 0; playing = false }
    return Math.round(buf * 1000) / 1000
  })
}

function demoRun(mode) {
  const host = []
  for (let t = 0; t <= 60; t++) {
    const load = t >= 10 && t < 50
    const hurt = load && (mode === 'baseline' || t < 16)
    const loss = hurt ? (mode === 'baseline' ? 30 + wobble(t, 8) : 0) : 0
    const v = VIDEO * (1 - loss / 100)
    host.push({
      t, video_mbps: Math.round(v * 1000) / 1000, video_loss_pct: Math.round(loss * 100) / 100,
      video_jitter_ms: hurt ? (mode === 'baseline' ? 0.5 + wobble(t, 0.1) : 0.2) : 0.08,
      ping_ms: hurt ? (mode === 'baseline' ? 30 + wobble(t, 1) : 2 + wobble(t, 0.5)) : 0.12,
      ping_lost: hurt && mode === 'baseline' && t % 3 === 0 ? 2 : 0,
      bg_mbps: load ? (mode === 'baseline' ? 7 + wobble(t, 0.5) : 9) : null,
      bg_loss_pct: load ? (mode === 'baseline' ? 20 + wobble(t, 4) : 0) : null,
      buffer_s: null,
    })
  }
  const levels = playout(host.map((h) => h.video_mbps * 1e6), VIDEO * 1e6)
  host.forEach((h, i) => { h.buffer_s = levels[i] })
  const controller = []
  for (let t = 0; t <= 60; t += 2) {
    const load = t >= 10 && t < 50
    const onB = mode === 'qos' && t >= 16
    const a = (load ? 9.27 : 0) + (onB ? 0 : 4.12)
    controller.push({ t, video_path: onB ? 'B' : 'A', congested: load && t >= 16 ? ['s4->s2', 's2->s1'] : [],
      'util_s4->s2': Math.min(1, a / 10), 'mbps_s4->s2': Math.min(10, a),
      'util_s2->s1': Math.min(1, a / 10), 'mbps_s2->s1': Math.min(10, a),
      'util_s4->s3': onB ? 0.412 : 0, 'mbps_s4->s3': onB ? 4.12 : 0,
      'util_s3->s1': onB ? 0.412 : 0, 'mbps_s3->s1': onB ? 4.12 : 0,
      video_mbps_s2: onB ? 0 : 4.1, video_mbps_s3: onB ? 4.1 : 0 })
  }
  const events = [{ demo: true, t: 16.0, event: 'congestion_detected', link: 's4->s2' }]
  if (mode === 'qos') events.push({ demo: true, t: 16.0, event: 'reroute', from_path: 'A', to_path: 'B' },
    { demo: true, t: 16.0, event: 'reroute_confirmed', install_ms: 10 })
  events.push({ demo: true, t: 56.0, event: 'congestion_cleared', link: 's4->s2' })
  return {
    demo: true, run: `${mode}-heavy-run1`, mode, load: 'heavy', bg_mbps: 9, valid: true, experiment: 'demo-experiment',
    timeline: demoExperiment.meta.timeline, host, controller, events,
    sources: { host: 'DEMO DATA (no hosts)', controller: 'DEMO DATA (no controller)', model: 'playout buffer model (startup 2.0 s, resume 1.0 s), fed with demo data' },
  }
}

export const demoRuns = { 'baseline-heavy-run1': demoRun('baseline'), 'qos-heavy-run1': demoRun('qos') }
