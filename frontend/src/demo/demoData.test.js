// Run with: npm test
import { describe, expect, it } from 'vitest'
import * as demo from './demoData'
import { num, range } from '../lib/format'
import { latestRun } from '../lib/runs'

const responses = {
  status: demo.demoStatus(), metrics: demo.demoMetrics(), events: demo.demoEvents(), host: demo.demoHost(),
  flows: demo.demoFlows(), topology: demo.demoTopology(), queues: demo.demoQueues(),
  settings: demo.demoSettings, environment: demo.demoEnvironment, experiment: demo.demoExperiment,
  ...demo.demoRuns,
}

describe('demo data is always marked as demo', () => {
  for (const [name, r] of Object.entries(responses)) {
    it(name, () => expect(r.demo).toBe(true))
  }
  it('every metric, event and host sample row', () => {
    for (const rows of [responses.metrics.metrics, responses.events.events, responses.host.samples]) {
      expect(rows.length).toBeGreaterThan(0)
      rows.forEach((x) => expect(x.demo).toBe(true))
    }
  })
  it('the experiment says it is not measured', () => {
    expect(demo.demoExperiment.summary.note).toMatch(/DEMO DATA/)
  })
})

describe('demo scenario', () => {
  it('starts with history: rerouted to Path B with Path A congested', () => {
    expect(responses.status.video_path).toBe('B')
    expect(responses.status.congested_links).toContain('s4->s2')
    expect(responses.events.events.map((e) => e.event)).toContain('reroute')
  })
  it('uses the same field names as the real config', () => {
    expect(demo.demoSettings.monitoring.cooldown_s).toBe(20)
    expect(demo.demoSettings.queues.video_min_mbps).toBe(6)
  })
})

describe('helpers', () => {
  it('formats numbers', () => {
    expect(num(4.0)).toBe('4')
    expect(num(0.12345, 3)).toBe('0.123')
    expect(num(null)).toBe('n/a')
    expect(num(11155)).toBe('11,155')
    expect(range({ mean: 2.5, min: 2.2, max: 3.24 })).toBe('2.5 (2.2 to 3.24)')
  })
  it('keeps only the latest lab run', () => {
    expect(latestRun([{ run_id: 'a' }, { run_id: 'b' }, { run_id: 'b' }])).toHaveLength(2)
    expect(latestRun([])).toEqual([])
  })
})
