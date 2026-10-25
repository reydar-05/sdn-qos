import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import { ModeProvider } from './lib/mode'
import Layout from './components/Layout'
import Overview from './pages/Overview'
import Topology from './pages/Topology'
import Monitoring from './pages/Monitoring'
import Experiments from './pages/Experiments'
import Events from './pages/Events'

// HashRouter (#/topology) works on any static host, Vercel included, with no rewrite rules.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ModeProvider>
      <HashRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="topology" element={<Topology />} />
            <Route path="monitoring" element={<Monitoring />} />
            <Route path="experiments" element={<Experiments />} />
            <Route path="events" element={<Events />} />
            <Route path="*" element={<Overview />} />
          </Route>
        </Routes>
      </HashRouter>
    </ModeProvider>
  </StrictMode>,
)
