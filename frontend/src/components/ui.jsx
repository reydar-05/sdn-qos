import { AlertTriangle, CheckCircle2, CircleSlash, Loader2, ServerCrash, WifiOff } from 'lucide-react'
import { useMode } from '../lib/mode'

export function DemoStamp({ className = '' }) {
  const { isDemo } = useMode()
  if (!isDemo) return null
  return (
    <span className={`inline-flex items-center rounded border border-warning bg-demo-bg px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-demo-ink ${className}`}>
      DEMO DATA
    </span>
  )
}

const SOURCE_TEXT = {
  controller: 'Controller (OpenFlow port stats)',
  host: 'End hosts (iperf3, ping)',
  model: 'Playout buffer model',
  tc: 'Kernel tc counters',
  config: 'config/config.yaml',
  verify: 'Verification logs',
}

export function SourceTag({ source }) {
  return (
    <span className="inline-flex items-center rounded bg-surface-2 px-1.5 py-0.5 text-[11px] font-medium text-ink-2">
      Source: {SOURCE_TEXT[source] || source}
    </span>
  )
}

export function Card({ title, subtitle, source, actions, children, className = '' }) {
  return (
    <section className={`rounded-lg border border-line bg-surface p-4 ${className}`}>
      {(title || actions) && (
        <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {source && <SourceTag source={source} />}
            <DemoStamp />
            {actions}
          </div>
        </header>
      )}
      {children}
    </section>
  )
}

export function PageHeader({ title, children }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold text-ink">
          {title} <DemoStamp />
        </h1>
        {children && <p className="mt-1 max-w-3xl text-sm text-ink-2">{children}</p>}
      </div>
    </div>
  )
}

export function Loading({ label = 'Loading' }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-ink-3">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}
    </div>
  )
}

/** Shown in LIVE LAB mode when data cannot be fetched. Never replaced by demo data. */
export function ErrorState({ error, title = 'Live data unavailable', hint }) {
  const Icon = error?.kind === 'network' || error?.kind === 'timeout' ? WifiOff : ServerCrash
  return (
    <div role="alert" className="rounded-lg border border-critical bg-error-bg p-4 text-error-ink">
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
        <div className="min-w-0 text-sm">
          <p className="font-semibold">{title}</p>
          <p className="mt-1 break-words">{error?.message || String(error)}</p>
          {hint && <div className="mt-2 text-xs opacity-90">{hint}</div>}
          <p className="mt-2 text-xs opacity-90">LIVE LAB mode never shows demo numbers instead. Switch to DEMO MODE to see sample data.</p>
        </div>
      </div>
    </div>
  )
}

export function StatusPill({ state, label }) {
  const map = {
    good: { Icon: CheckCircle2, cls: 'text-good-ink', dot: 'bg-good' },
    bad: { Icon: AlertTriangle, cls: 'text-critical-ink', dot: 'bg-critical' },
    warn: { Icon: AlertTriangle, cls: 'text-ink', dot: 'bg-warning' },
    off: { Icon: CircleSlash, cls: 'text-ink-3', dot: 'bg-ink-3' },
  }
  const { Icon, cls } = map[state] || map.off
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm font-medium ${cls}`}>
      <Icon className="h-4 w-4" aria-hidden /> {label}
    </span>
  )
}

export function StatTile({ label, value, unit, note, children }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-ink-2">{label}</p>
        <DemoStamp />
      </div>
      <div className="mt-2 text-2xl font-semibold text-ink tabular">
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-ink-3">{unit}</span>}
      </div>
      {children}
      {note && <p className="mt-1 text-xs text-ink-3">{note}</p>}
    </div>
  )
}

/** Utilization bar: blue track, warning above 70% of threshold, critical when congested. */
export function Meter({ value, threshold = 0.8, congested }) {
  const v = Math.max(0, Math.min(1, value ?? 0))
  const color = congested ? 'bg-critical' : v >= threshold ? 'bg-warning' : 'bg-qos'
  return (
    <div className="relative h-2 w-full rounded-full bg-surface-2" aria-hidden>
      <div className={`h-2 rounded-full ${color}`} style={{ width: `${v * 100}%` }} />
      <div className="absolute top-[-3px] h-3.5 w-0.5 bg-ink-3" style={{ left: `${threshold * 100}%` }} title="threshold" />
    </div>
  )
}

export function KeyValue({ rows }) {
  return (
    <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1.5 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-2">{k}</dt>
          <dd className="text-right font-medium text-ink tabular">{v}</dd>
        </div>
      ))}
    </dl>
  )
}
