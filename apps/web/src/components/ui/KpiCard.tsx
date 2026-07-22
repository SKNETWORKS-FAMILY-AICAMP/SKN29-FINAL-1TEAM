export function KpiCard({
  label,
  value,
  unit,
  warn,
}: {
  label: string
  value: string | number
  unit?: string
  warn?: boolean
}) {
  return (
    <div className={'kpi' + (warn ? ' warn' : '')}>
      <div className="label">{label}</div>
      <div className="value">
        {value}
        {unit && <small>{unit}</small>}
      </div>
    </div>
  )
}
