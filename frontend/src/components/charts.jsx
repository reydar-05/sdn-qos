/*
 * Chart wrappers on top of Recharts, so every chart looks and behaves the
 * same: 2px lines, hairline grid, one y-axis, legend for 2+ series, a hover
 * tooltip, a DEMO DATA stamp in demo mode and a "Table" toggle that shows
 * the same numbers as text.
 */
import { useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Table2, LineChart as LineIcon } from 'lucide-react'
import { Card } from './ui'
import { num } from '../lib/format'

function TooltipBox({ active, payload, label, xLabel, unit, digits, xFormat }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium text-ink">{xFormat ? xFormat(label) : xLabel ? `${xLabel} ${label}` : label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} className="flex items-center gap-2 text-ink-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.color }} />
          {p.name}: <span className="font-medium text-ink tabular">{num(p.value, digits)}{unit ? ` ${unit}` : ''}</span>
        </p>
      ))}
    </div>
  )
}

function DataTable({ rows, xKey, xLabel, series, unit, digits, xFormat }) {
  return (
    <div className="max-h-72 overflow-auto rounded border border-line">
      <table className="w-full text-xs tabular">
        <thead className="sticky top-0 bg-surface-2 text-ink-2">
          <tr>
            <th className="px-2 py-1 text-left font-medium">{xLabel || xKey}</th>
            {series.map((s) => <th key={s.key} className="px-2 py-1 text-right font-medium">{s.label}{unit ? ` (${unit})` : ''}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-line">
              <td className="px-2 py-1 text-ink-2">{xFormat ? xFormat(r[xKey]) : r[xKey]}</td>
              {series.map((s) => <td key={s.key} className="px-2 py-1 text-right text-ink">{num(r[s.key], digits)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TableToggle({ table, setTable }) {
  return (
    <button type="button" onClick={() => setTable(!table)}
      className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-[11px] text-ink-2 hover:bg-surface-2"
      aria-pressed={table}>
      {table ? <LineIcon className="h-3 w-3" aria-hidden /> : <Table2 className="h-3 w-3" aria-hidden />}
      {table ? 'Chart' : 'Table'}
    </button>
  )
}

const axisProps = { stroke: 'var(--border)', tickLine: false, tick: { fill: 'var(--ink-3)', fontSize: 11 } }

/**
 * series: [{ key, label, color }]
 * marks:  vertical event lines [{ x, label }]
 * bands:  shaded x ranges [{ x1, x2, label }] (e.g. background traffic period)
 */
export function TimeChart({
  title, subtitle, source, rows, xKey = 't', xLabel = 't (s)', series, unit, digits = 2,
  yDomain, threshold, thresholdLabel, marks = [], bands = [], height = 220, empty, xFormat,
}) {
  const [table, setTable] = useState(false)
  const hasData = rows?.some((r) => series.some((s) => r[s.key] !== null && r[s.key] !== undefined))
  return (
    <Card title={title} subtitle={subtitle} source={source} actions={hasData && <TableToggle table={table} setTable={setTable} />}>
      {!hasData ? (
        <p className="py-8 text-center text-sm text-ink-3">{empty || 'No data for this chart yet.'}</p>
      ) : table ? (
        <DataTable rows={rows} xKey={xKey} xLabel={xLabel} series={series} unit={unit} digits={digits} xFormat={xFormat} />
      ) : (
        <div style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: marks.length ? 20 : 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              {bands.map((b) => (
                <ReferenceArea key={b.label} x1={b.x1} x2={b.x2} fill="var(--ink-3)" fillOpacity={0.07} ifOverflow="extendDomain"
                  label={{ value: b.label, position: 'insideTopLeft', fill: 'var(--ink-3)', fontSize: 10 }} />
              ))}
              <XAxis dataKey={xKey} type="number" domain={['dataMin', 'dataMax']} tickFormatter={xFormat} {...axisProps} />
              <YAxis width={44} domain={yDomain || ['auto', 'auto']} {...axisProps}
                tickFormatter={(v) => num(v, 2)} label={unit ? { value: unit, angle: -90, position: 'insideLeft', fill: 'var(--ink-3)', fontSize: 11 } : undefined} />
              {threshold !== undefined && (
                <ReferenceLine y={threshold} stroke="var(--ink-3)" strokeDasharray="4 3"
                  label={{ value: thresholdLabel || `threshold ${threshold}`, position: 'insideTopRight', fill: 'var(--ink-2)', fontSize: 10 }} />
              )}
              {marks.map((m, i) => (
                <ReferenceLine key={`${m.x}-${i}`} x={m.x} stroke="var(--ink-2)" strokeWidth={1}
                  label={{ value: m.label, position: 'top', fill: 'var(--ink-2)', fontSize: 10 }} />
              ))}
              <Tooltip content={<TooltipBox xLabel={xLabel} unit={unit} digits={digits} xFormat={xFormat} />} cursor={{ stroke: 'var(--ink-3)', strokeWidth: 1 }} />
              {series.length > 1 && <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />}
              {series.map((s) => (
                <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2}
                  dot={false} activeDot={{ r: 4, stroke: 'var(--surface)', strokeWidth: 2 }} connectNulls={false} isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

/** Grouped bars, e.g. baseline vs QoS for light and heavy load. */
export function GroupBars({ title, subtitle, source, rows, xKey, series, unit, digits = 2, height = 220, note }) {
  const [table, setTable] = useState(false)
  return (
    <Card title={title} subtitle={subtitle} source={source} actions={<TableToggle table={table} setTable={setTable} />}>
      {table ? (
        <DataTable rows={rows} xKey={xKey} xLabel="load" series={series} unit={unit} digits={digits} />
      ) : (
        <div style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 16, right: 12, bottom: 0, left: 0 }} barGap={2} barCategoryGap="30%">
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey={xKey} {...axisProps} />
              <YAxis width={44} {...axisProps} tickFormatter={(v) => num(v, 2)} />
              <Tooltip content={<TooltipBox unit={unit} digits={digits} />} cursor={{ fill: 'var(--surface-2)' }} />
              <Legend iconType="square" wrapperStyle={{ fontSize: 12 }} />
              {series.map((s) => (
                <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} maxBarSize={24} radius={[4, 4, 0, 0]}
                  isAnimationActive={false}
                  label={({ x, y, width, value }) => (value === null || value === undefined ? null : (
                    <text x={x + width / 2} y={y - 5} textAnchor="middle" fontSize={11} fill="var(--ink-2)">{num(value, digits)}</text>
                  ))} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {note && <p className="mt-2 text-xs text-ink-3">{note}</p>}
    </Card>
  )
}
