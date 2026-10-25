import { Card, ErrorState, Loading, PageHeader, StatusPill } from '../components/ui'
import { BackendHint } from '../components/LiveHints'
import { useData } from '../lib/useData'
import { num, pct } from '../lib/format'

// Fixed drawing positions (viewBox 760 x 300)
const POS = { h1: [60, 85], h3: [60, 215], s1: [220, 150], s2: [400, 60], s3: [400, 240], s4: [580, 150], h2: [700, 150] }
const PATH_OF = { 's1-s2': 'A', 's2-s4': 'A', 's1-s3': 'B', 's3-s4': 'B' }
const HOST_ROLE = { client: 'video client', server: 'video server', background: 'background' }

function linkInfo(l) {
  const dirs = Object.entries(l.directions || {}).filter(([, v]) => v)
  if (!dirs.length) return null
  const [dir, d] = dirs.reduce((a, b) => ((b[1].utilization ?? 0) > (a[1].utilization ?? 0) ? b : a))
  return { dir, ...d, congested: dirs.some(([, v]) => v.congested) }
}

function Diagram({ topo, live }) {
  const videoPath = live ? topo.video_path : null
  return (
    <svg viewBox="0 0 780 300" className="h-auto w-full" role="img"
      aria-label={`Topology: h1 and h3 on s1, h2 on s4, Path A through s2, Path B through s3${videoPath ? `, video on Path ${videoPath}` : ''}`}>
      {Object.entries(topo.hosts).map(([h, info]) => {
        const [x1, y1] = POS[h]; const [x2, y2] = POS[info.switch]
        return <line key={h} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--ink-3)" strokeWidth={1.5} />
      })}
      {topo.links.map((l) => {
        const key = `${l.a}-${l.b}`
        const path = PATH_OF[key]
        const [x1, y1] = POS[l.a]; const [x2, y2] = POS[l.b]
        const info = live ? linkInfo(l) : null
        const onVideo = videoPath === path
        const color = info?.congested ? 'var(--critical)' : path === 'A' ? 'var(--path-a)' : 'var(--path-b)'
        const mx = (x1 + x2) / 2; const my = (y1 + y2) / 2
        const above = path === 'A'
        const left = l.a === 's1' // links leaving s1 sit on the left half
        const tx = left ? mx - 14 : mx + 14
        const anchor = left ? 'end' : 'start'
        const ty = above ? my - 22 : my + 20
        return (
          <g key={key}>
            {onVideo && <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--video)" strokeOpacity={0.25} strokeWidth={14} strokeLinecap="round" />}
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={onVideo ? 4 : 2.5}
              strokeDasharray={info?.congested ? '7 4' : undefined} strokeLinecap="round" />
            <text x={tx} y={ty} textAnchor={anchor} fontSize="11" fill="var(--ink-2)">
              <tspan x={tx} dy="0">{l.capacity_mbps} Mbit/s</tspan>
              {info && <tspan x={tx} dy="13">peak {pct(info.utilization)} ({info.dir})</tspan>}
              {info?.congested && <tspan x={tx} dy="13" fontWeight="600" fill="var(--critical-ink)">congested</tspan>}
            </text>
          </g>
        )
      })}
      {Object.entries(POS).map(([n, [x, y]]) => {
        const isSwitch = n.startsWith('s')
        return (
          <g key={n}>
            {isSwitch
              ? <rect x={x - 24} y={y - 18} width={48} height={36} rx={6} fill="var(--surface)" stroke="var(--ink-2)" strokeWidth={1.5} />
              : <circle cx={x} cy={y} r={20} fill="var(--surface-2)" stroke="var(--ink-3)" strokeWidth={1.5} />}
            <text x={x} y={y + 4} textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--ink)">{n}</text>
            {!isSwitch && topo.hosts[n] && (
              <text x={x} y={y + 36} textAnchor="middle" fontSize="10" fill="var(--ink-3)">
                {topo.hosts[n].ip}, {HOST_ROLE[topo.hosts[n].role] || topo.hosts[n].role}
              </text>
            )}
          </g>
        )
      })}
      <text x={400} y={16} textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--ink-2)">Path A (default)</text>
      <text x={400} y={292} textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--ink-2)">Path B (alternative)</text>
    </svg>
  )
}

function Legend({ live, topo }) {
  const item = (style, label) => (
    <span className="inline-flex items-center gap-1.5"><span className="inline-block h-1 w-6 rounded" style={style} />{label}</span>
  )
  return (
    <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-2">
      {item({ background: 'var(--path-a)' }, 'Path A: s1, s2, s4')}
      {item({ background: 'var(--path-b)' }, 'Path B: s1, s3, s4')}
      {item({ background: 'var(--video)', opacity: 0.4, height: 8 }, `current video path${live && topo.video_path ? ` (Path ${topo.video_path})` : ''}`)}
      {item({ background: 'repeating-linear-gradient(90deg, var(--critical) 0 6px, transparent 6px 9px)' }, 'congested (above threshold for 3 polls)')}
    </div>
  )
}

export default function Topology() {
  const topo = useData('topology', { interval: 2000 })
  if (topo.error) return (<div className="space-y-4"><PageHeader title="Topology" /><ErrorState error={topo.error} title="Backend not reachable" hint={<BackendHint />} /></div>)
  if (!topo.data) return <Loading />
  const t = topo.data
  const live = t.controller?.reachable
  return (
    <div className="space-y-4">
      <PageHeader title="Topology">
        Four Open vSwitch switches with a loop: two paths between the client side (s1) and the server side (s4).
        There is no flooding; the controller installs every path itself and answers ARP.
      </PageHeader>
      {!live && (
        <ErrorState error={{ message: t.controller?.reason || 'controller not reachable' }}
          title="Live link state unavailable: showing the configured topology only" />
      )}
      <Card title="Network" subtitle="Link labels show capacity and the busier direction's utilization" source={live ? 'controller' : 'config'}>
        <Diagram topo={t} live={live} />
        <Legend live={live} topo={t} />
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Links" source={live ? 'controller' : 'config'}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] text-sm">
              <thead className="text-left text-xs text-ink-3">
                <tr><th className="py-1 font-medium">Link (ports)</th><th className="py-1 font-medium">Path</th><th className="py-1 font-medium">Capacity</th><th className="py-1 font-medium">Directions now</th></tr>
              </thead>
              <tbody>
                {t.links.map((l) => (
                  <tr key={`${l.a}-${l.b}`} className="border-t border-line align-top">
                    <td className="py-1.5 font-mono text-xs text-ink">{l.a}:{l.a_port} to {l.b}:{l.b_port}</td>
                    <td className="py-1.5 text-ink-2">{PATH_OF[`${l.a}-${l.b}`]}</td>
                    <td className="py-1.5 tabular text-ink-2">{l.capacity_mbps} Mbit/s</td>
                    <td className="py-1.5 text-xs tabular text-ink-2">
                      {live && l.directions ? Object.entries(l.directions).map(([d, v]) => (
                        <div key={d}>{d}: {v ? `${num(v.mbps)} Mbit/s, ${pct(v.utilization)}` : 'no data'}{v?.congested ? ' (congested)' : ''}</div>
                      )) : 'no live data'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Hosts and paths" source="config">
          <ul className="space-y-1.5 text-sm text-ink-2">
            {Object.entries(t.hosts).map(([h, info]) => (
              <li key={h}><span className="font-medium text-ink">{h}</span> {info.ip} on {info.switch} port {info.port}, {HOST_ROLE[info.role] || info.role}</li>
            ))}
          </ul>
          <div className="mt-3 space-y-1 text-sm text-ink-2">
            {Object.entries(t.paths).map(([p, sw]) => (
              <p key={p}>Path {p}: {sw.join(', ')}{p === t.primary_path ? ' (default)' : ''}
                {live && t.video_path === p ? <span className="ml-2"><StatusPill state="good" label="carries video now" /></span> : null}</p>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
