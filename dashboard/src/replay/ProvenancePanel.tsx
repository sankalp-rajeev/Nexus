import { sourceUrl, type ReplayData } from '../replay'
import { Mono } from './ui'

const SEALED_PREFIX = 'data/nexusbench/'

export default function ProvenancePanel({ data }: { data: ReplayData }) {
  const p = data.provenance
  const main = p.phase5_runs.main_run as { records_sha256: string; verified_against: string; records: number }
  const selection = (p.phase5_runs.selection ?? []) as { rule: string; run: string; describes: string; matches: number; selected: string }[]
  return (
    <div className="space-y-6 text-sm" aria-label="Provenance">
      <p className="border border-accent bg-accentsoft rounded-lg p-3">{p.data_statement}.</p>
      <dl className="grid sm:grid-cols-[12rem_1fr] gap-x-4 gap-y-1 text-xs">
        <dt className="text-muted">Exported from commit</dt><dd><a className="underline text-cool" href={`${p.repository}/commit/${p.generated_from_commit}`} target="_blank" rel="noreferrer"><Mono>{p.generated_from_commit}</Mono></a></dd>
        <dt className="text-muted">Exporter</dt><dd><a className="underline text-cool" href={sourceUrl(data, p.exporter)} target="_blank" rel="noreferrer"><Mono>{p.exporter}</Mono></a></dd>
        <dt className="text-muted">Model calls while exporting</dt><dd>{p.llm_calls}</dd>
        <dt className="text-muted">Heal source</dt><dd>{p.phase5_runs_location}</dd>
        <dt className="text-muted">Run records SHA-256</dt><dd><Mono>{main.records_sha256}</Mono> over {main.records} records, equal to <Mono>{main.verified_against}</Mono></dd>
      </dl>
      <section>
        <h3 className="font-semibold mb-1">Selection rule</h3>
        <p className="text-xs text-ink2"><span className="font-medium">Traces.</span> {p.selection_rule.traces}</p>
        <p className="text-xs text-ink2 mt-1"><span className="font-medium">Heals.</span> {p.selection_rule.heals}</p>
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-xs border-collapse">
            <thead><tr className="border-b border-rule text-left text-muted"><th className="py-1 pr-3">Rule</th><th className="pr-3">Run</th><th className="pr-3">Matches</th><th>Selected</th></tr></thead>
            <tbody>
              {selection.map(row => (
                <tr key={row.rule} className="border-b border-rule align-top">
                  <td className="py-1 pr-3">{row.describes}</td><td className="pr-3 font-mono">{row.run}</td>
                  <td className="pr-3 tabular-nums">{row.matches}</td><td className="font-mono">{row.selected}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section>
        <h3 className="font-semibold mb-1">Source files (git blob ids)</h3>
        <ul className="text-xs space-y-1">
          {Object.entries(p.sources).map(([path, blob]) => (
            <li key={path} className="break-all">
              {path.startsWith(SEALED_PREFIX)
                ? <span>{path} <span className="text-muted">(holds sealed TEST rows: named, not linked; only DEV rows are read, via the DEV adapter)</span></span>
                : <a className="underline text-cool" href={sourceUrl(data, path)} target="_blank" rel="noreferrer">{path}</a>} <span className="font-mono text-muted">{blob}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
