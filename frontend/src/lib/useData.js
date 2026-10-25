/*
 * One hook for every page: useData('status'), useData('metrics'), ...
 * DEMO MODE: answers come from src/demo/demoData.js (marked demo: true).
 * LIVE LAB:  answers come from Flask. On any error the data is cleared and
 *            the error is returned, so a page can never show old or demo
 *            numbers as if they were live.
 */
import { useEffect, useRef, useState } from 'react'
import { apiGet } from './api'
import { useMode } from './mode'
import * as demo from '../demo/demoData'

const SOURCES = {
  health: { path: () => '/api/health', demo: () => ({ demo: true, ok: true }) },
  status: { path: () => '/api/status', demo: demo.demoStatus },
  metrics: { path: () => '/api/metrics?limit=150', demo: () => demo.demoMetrics(150) },
  events: { path: () => '/api/events?limit=500', demo: demo.demoEvents },
  host: { path: () => '/api/host?limit=120', demo: () => demo.demoHost(120) },
  flows: { path: () => '/api/flows', demo: demo.demoFlows },
  topology: { path: () => '/api/topology', demo: demo.demoTopology },
  queues: { path: () => '/api/queues', demo: demo.demoQueues },
  settings: { path: () => '/api/settings', demo: () => demo.demoSettings },
  experiment: { path: () => '/api/experiments/latest', demo: () => demo.demoExperiment },
  environment: { path: () => '/api/environment', demo: () => demo.demoEnvironment },
  timeseries: {
    path: ({ exp, run }) => `/api/experiments/${encodeURIComponent(exp)}/runs/${encodeURIComponent(run)}/timeseries`,
    demo: ({ run }) => demo.demoRuns[run] || null,
  },
}

export function useData(key, { interval = 0, params = {}, enabled = true } = {}) {
  const { mode, apiBase, token } = useMode()
  const src = SOURCES[key]
  const paramKey = JSON.stringify(params)
  const [state, setState] = useState({ data: null, error: null, loading: true, updatedAt: null })
  const gen = useRef(0)

  useEffect(() => {
    const my = ++gen.current
    // start empty whenever the mode, backend or parameters change
    setState({ data: null, error: null, loading: enabled, updatedAt: null })
    if (!enabled) return undefined
    const p = JSON.parse(paramKey)
    let timer = null
    const load = async () => {
      try {
        const data = mode === 'demo' ? src.demo(p) : await apiGet(src.path(p), { base: apiBase, token })
        if (gen.current !== my) return
        if (mode === 'demo' && !data) throw new Error('no demo data for this item')
        setState({ data, error: null, loading: false, updatedAt: Date.now() })
      } catch (error) {
        if (gen.current !== my) return
        setState({ data: null, error, loading: false, updatedAt: Date.now() })
      }
    }
    load()
    if (interval) timer = setInterval(load, interval)
    return () => { if (timer) clearInterval(timer); gen.current++ }
  }, [mode, apiBase, token, key, paramKey, interval, enabled]) // eslint-disable-line react-hooks/exhaustive-deps

  return { ...state, mode }
}
