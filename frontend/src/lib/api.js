/*
 * Talks to the Flask backend (LIVE LAB mode only). Every failure becomes an
 * ApiError with a plain explanation. There is no fallback to demo data here:
 * the caller shows the error.
 */

export const DEFAULT_API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:5000').replace(/\/+$/, '')

export class ApiError extends Error {
  constructor(kind, message, status) {
    super(message)
    this.kind = kind // 'network' | 'auth' | 'http' | 'timeout' | 'bad-json'
    this.status = status
  }
}

export async function apiGet(path, { base = DEFAULT_API_BASE, token, timeoutMs = 5000 } = {}) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  const headers = { Accept: 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  let res
  try {
    res = await fetch(`${base}${path}`, { headers, signal: ctrl.signal })
  } catch (e) {
    if (e.name === 'AbortError') throw new ApiError('timeout', `No answer from the backend at ${base} within ${timeoutMs / 1000} s`)
    throw new ApiError('network', `Cannot reach the backend at ${base} (is Flask running, and is this origin in the CORS allowlist?)`)
  } finally {
    clearTimeout(timer)
  }
  let body = null
  try {
    body = await res.json()
  } catch {
    throw new ApiError('bad-json', `Backend answered ${res.status} without JSON for ${path}`, res.status)
  }
  if (res.status === 401) throw new ApiError('auth', 'The backend needs an API token (set it under Connection)', 401)
  if (!res.ok) throw new ApiError('http', body?.error || `Backend error ${res.status} for ${path}`, res.status)
  return body
}
