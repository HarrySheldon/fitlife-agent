import { Cell, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

interface ChartCardProps {
  title: string
  data: Array<Record<string, string | number>>
  type?: 'line' | 'pie'
  referenceValue?: number
  referenceLabel?: string
}

const COLORS = ['#216869', '#49a078', '#d7b377', '#8f5c38']

export function ChartCard({ title, data, type = 'line', referenceValue, referenceLabel }: ChartCardProps) {
  return (
    <section className="chart-card">
      <h2>{title}</h2>
      <div className="chart-area">
        <ResponsiveContainer width="100%" height="100%">
          {type === 'pie' ? (
            <PieChart>
              <Pie data={data} dataKey="value" nameKey="name" innerRadius={42} outerRadius={74}>
                {data.map((_, index) => (
                  <Cell key={index} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          ) : (
            <LineChart data={data}>
              <XAxis dataKey={data[0]?.date ? 'date' : 'week'} hide />
              <YAxis width={42} />
              <Tooltip />
              {referenceValue && referenceValue > 0 ? (
                <ReferenceLine
                  y={referenceValue}
                  stroke="#8f5c38"
                  strokeDasharray="4 4"
                  label={referenceLabel ? { value: referenceLabel, position: 'insideTopRight', fill: '#8f5c38', fontSize: 11 } : undefined}
                />
              ) : null}
              <Line type="monotone" dataKey="value" stroke="#216869" strokeWidth={3} dot={false} />
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </section>
  )
}
