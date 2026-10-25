/*
 * LIVE LAB / DEMO MODE switch.
 * - The starting mode comes from ?mode=live|demo in the URL, then the
 *   viewer's last choice, then VITE_DEFAULT_MODE, then live.
 * - The backend address and optional API token can be changed in the
 *   Connection panel; they are kept in this browser only.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { DEFAULT_API_BASE } from './api'

const ModeContext = createContext(null)

function readStore(key) {
  try { return window.localStorage.getItem(key) } catch { return null }
}
function writeStore(key, value) {
  try {
    if (value) window.localStorage.setItem(key, value)
    else window.localStorage.removeItem(key)
  } catch { /* storage blocked: the setting lasts for this visit only */ }
}

const valid = (m) => (m === 'live' || m === 'demo' ? m : null)

function initialMode() {
  let fromUrl = null
  try { fromUrl = new URLSearchParams(window.location.search).get('mode') } catch { /* ignore */ }
  return valid(fromUrl) || valid(readStore('sdnqos.mode')) || valid(import.meta.env.VITE_DEFAULT_MODE) || 'live'
}

export function ModeProvider({ children }) {
  const [mode, setModeState] = useState(initialMode)
  const [apiBase, setApiBaseState] = useState(() => readStore('sdnqos.apiBase') || DEFAULT_API_BASE)
  const [token, setTokenState] = useState(() => readStore('sdnqos.token') || '')

  const setMode = useCallback((m) => { setModeState(m); writeStore('sdnqos.mode', m) }, [])
  const setApiBase = useCallback((b) => {
    const clean = (b || '').trim().replace(/\/+$/, '')
    setApiBaseState(clean || DEFAULT_API_BASE)
    writeStore('sdnqos.apiBase', clean && clean !== DEFAULT_API_BASE ? clean : null)
  }, [])
  const setToken = useCallback((t) => { setTokenState(t); writeStore('sdnqos.token', t || null) }, [])

  useEffect(() => { document.documentElement.dataset.mode = mode }, [mode])

  const value = useMemo(() => ({ mode, isDemo: mode === 'demo', setMode, apiBase, setApiBase, token, setToken }),
    [mode, setMode, apiBase, setApiBase, token, setToken])
  return <ModeContext.Provider value={value}>{children}</ModeContext.Provider>
}

export function useMode() {
  const ctx = useContext(ModeContext)
  if (!ctx) throw new Error('useMode outside ModeProvider')
  return ctx
}
