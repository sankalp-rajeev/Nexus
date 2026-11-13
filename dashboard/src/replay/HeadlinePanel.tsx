import { sourceUrl, type ReplayData } from '../replay'

export default function HeadlinePanel({ data }: { data: ReplayData }) {
  return (
    <div className="space-y-6" aria-label="Headline numbers">
      <p className="text-sm text-stone-600">
        Every number below is parsed from the file named under it, at the commit this page was exported from. {data.provenance.data_statement}.
      </p>
      {data.headline.groups.map(group => (
        <section key={group.title} aria-label={group.title}>
          <h3 className="text-sm font-semibold mb-2">{group.title}</h3>
          <ul className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {group.items.map(item => (
              <li key={item.id} data-headline={item.id} className="border border-stone-200 bg-white rounded-lg p-4 min-w-0">
                <p className="text-xs text-stone-500 leading-snug">{item.label}</p>
                <p className="text-lg font-semibold mt-1 break-words">{item.value}</p>
                <span className={`inline-block mt-1 text-xs font-mono px-2 py-0.5 rounded border ${item.scope.startsWith('TEST') ? 'bg-amber-50 border-amber-300 text-amber-800' : 'bg-stone-100 border-stone-200 text-stone-600'}`}>{item.scope}</span>
                {item.note && <p className="text-xs text-stone-500 mt-2 leading-snug">{item.note}</p>}
                <p className="text-xs mt-2 break-all">
                  Source: <a className="underline text-sky-800" href={sourceUrl(data, item.source.path)} target="_blank" rel="noreferrer">{item.source.path}</a>
                  <span className="block text-stone-400 font-mono">{item.source.locator}</span>
                </p>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
