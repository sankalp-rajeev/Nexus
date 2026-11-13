import { sourceUrl, type ReplayData } from '../replay'

export default function HeadlinePanel({ data }: { data: ReplayData }) {
  return (
    <div className="space-y-6" aria-label="Headline numbers">
      <p className="text-sm text-ink2">
        Every number below is parsed from the file named under it, at the commit this page was exported from. {data.provenance.data_statement}.
      </p>
      {data.headline.groups.map(group => (
        <section key={group.title} aria-label={group.title}>
          <h3 className="text-sm font-semibold mb-2">{group.title}</h3>
          <ul className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {group.items.map(item => (
              <li key={item.id} data-headline={item.id} className="border border-rule bg-paper2 rounded-lg p-4 min-w-0">
                <p className="text-xs text-muted leading-snug">{item.label}</p>
                <p className="text-lg font-semibold mt-1 break-words">{item.value}</p>
                <span className={`inline-block mt-1 text-xs font-mono px-2 py-0.5 rounded border ${item.scope.startsWith('TEST') ? 'bg-accentsoft border-accent text-accent' : 'bg-paper3 border-rule text-ink2'}`}>{item.scope}</span>
                {item.note && <p className="text-xs text-muted mt-2 leading-snug">{item.note}</p>}
                <p className="text-xs mt-2 break-all">
                  Source: <a className="underline text-cool" href={sourceUrl(data, item.source.path)} target="_blank" rel="noreferrer">{item.source.path}</a>
                  <span className="block text-muted font-mono">{item.source.locator}</span>
                </p>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
