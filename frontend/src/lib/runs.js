/** Rows of the most recent lab run only, so two runs are never drawn as one line. */
export function latestRun(rows) {
  if (!rows?.length) return []
  const id = rows[rows.length - 1].run_id
  return rows.filter((r) => r.run_id === id)
}
