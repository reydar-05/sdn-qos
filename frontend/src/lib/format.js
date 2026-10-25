export function num(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return 'n/a'
  const n = Number(v)
  if (!Number.isFinite(n)) return 'n/a'
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 })
  return String(parseFloat(n.toFixed(digits)))
}

export const pct = (v, digits = 0) => (v === null || v === undefined ? 'n/a' : `${(v * 100).toFixed(digits)}%`)

export function clock(ts) {
  if (!ts) return 'n/a'
  return new Date(ts * 1000).toLocaleTimeString([], { hour12: false })
}

export function dateTime(ts) {
  if (!ts) return 'n/a'
  return new Date(ts * 1000).toLocaleString([], { hour12: false })
}

/** "mean (min to max)" for a summary statistic. */
export function range(s, digits = 2) {
  if (!s || s.mean === null || s.mean === undefined) return 'n/a'
  if (s.min === s.max) return num(s.mean, digits)
  return `${num(s.mean, digits)} (${num(s.min, digits)} to ${num(s.max, digits)})`
}
