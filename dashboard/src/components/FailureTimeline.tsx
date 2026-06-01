import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from 'recharts'
import type { TimelineBucket } from '../types'

const FAILURE_COLORS: Record<string, string> = {
  HALLUCINATION: '#7c3aed',
  TOOL_MISFIRE:  '#ea580c',
  LOOP_DETECTED: '#dc2626',
  PLAN_DRIFT:    '#0284c7',
  CONTEXT_BLEED: '#0d9488',
}

interface ChartRow {
  hour: string
  [failure: string]: number | string
}

function buildChartData(buckets: TimelineBucket[]): ChartRow[] {
  const byHour: Record<string, ChartRow> = {}
  for (const b of buckets) {
    const hour = new Date(b.bucket).toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit',
    })
    if (!byHour[hour]) byHour[hour] = { hour }
    byHour[hour][b.failure_type] = (byHour[hour][b.failure_type] as number || 0) + b.count
  }
  return Object.values(byHour)
}

export default function FailureTimeline({ buckets }: { buckets: TimelineBucket[] }) {
  const data = buildChartData(buckets)
  const failureTypes = [...new Set(buckets.map(b => b.failure_type))].filter(f => f !== 'NORMAL')

  return (
    <section className="flex flex-col h-full">
      <header className="mb-3">
        <h2 className="text-sm font-semibold text-stone-800 tracking-tight">Failure Timeline</h2>
        <p className="text-xs text-stone-400 font-mono mt-0.5">Last 24 hours &bull; 1-hour buckets</p>
      </header>

      {data.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-stone-300 font-mono text-xs">
          No failures in last 24 hours
        </div>
      ) : (
        <div className="flex-1 min-h-0">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
              <XAxis
                dataKey="hour"
                tick={{ fontSize: 10, fontFamily: 'DM Mono', fill: '#a8a29e' }}
                tickLine={false}
                axisLine={{ stroke: '#e7e5e4' }}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 10, fontFamily: 'DM Mono', fill: '#a8a29e' }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  fontFamily: 'DM Mono',
                  border: '1px solid #e7e5e4',
                  borderRadius: 6,
                  background: '#fafaf9',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
                }}
              />
              <Legend
                wrapperStyle={{ fontSize: 11, fontFamily: 'DM Mono', paddingTop: 8 }}
              />
              {failureTypes.map(ft => (
                <Line
                  key={ft}
                  type="monotone"
                  dataKey={ft}
                  stroke={FAILURE_COLORS[ft] ?? '#78716c'}
                  strokeWidth={1.5}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  )
}
