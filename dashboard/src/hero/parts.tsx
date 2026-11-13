import { useEffect, useRef, useState } from 'react'
import type { ReplayData } from '../replay'
import { citeUrl, fileName } from './numbers'

type Cited = { cite: { path: string; line: number }; source: { path: string } }

/** Lands on the committed row; the visible text is the file and line, e.g. "test_scoring.md:27". */
export function SourceLink({ data, item, label }: { data: ReplayData; item: Cited; label?: string }) {
  const cite = `${fileName(item.cite.path)}:${item.cite.line}`
  return (
    <a className="nx-source" href={citeUrl(data, item.cite)} target="_blank" rel="noreferrer"
       aria-label={`${label ?? 'Source'}: ${item.cite.path} line ${item.cite.line}, via ${item.source.path} (opens on GitHub in a new tab)`}>
      {cite}
    </a>
  )
}

/** A link to where a term is defined, e.g. the preregistration's definition of a false promotion. */
export function DefinitionLink({ data, at }: { data: ReplayData; at: { path: string; line: number } }) {
  return (
    <a className="nx-source" href={citeUrl(data, at)} target="_blank" rel="noreferrer"
       aria-label={`Definition: ${at.path} line ${at.line} (opens on GitHub in a new tab)`}>
      definition
    </a>
  )
}

/** k/n read aloud as "k of n"; the slash is visual only. */
export function Fraction({ k, n }: { k: number; n: number }) {
  return (
    <>
      {k}<span className="nx-reading__of" aria-hidden="true">/{n}</span>
      <span className="visually-hidden"> of {n}</span>
    </>
  )
}

/** A command or snippet with a working copy button (real clipboard write, visible result). */
export function CopyBlock({ text, label, multiline = false }: { text: string; label: string; multiline?: boolean }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const code = useRef<HTMLElement>(null)
  useEffect(() => {
    if (state === 'idle') return
    const timer = window.setTimeout(() => setState('idle'), state === 'copied' ? 2000 : 6000)
    return () => window.clearTimeout(timer)
  }, [state])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setState('copied')
    } catch {
      // Clipboard refused (permissions, http): select the text so Ctrl+C works.
      const range = document.createRange()
      if (code.current) range.selectNodeContents(code.current)
      window.getSelection()?.removeAllRanges()
      window.getSelection()?.addRange(range)
      setState('failed')
    }
  }

  const shown = state === 'copied' ? 'Copied' : state === 'failed' ? 'Press Ctrl+C' : 'Copy'
  return (
    <div className={multiline ? 'nx-code' : 'nx-install'}>
      {multiline
        ? <pre className="nx-code__body" tabIndex={0} aria-label={label}><code ref={code}>{text}</code></pre>
        : <code ref={code} className="nx-install__cmd">{text}</code>}
      <button type="button" className={multiline ? 'btn btn--quiet nx-code__btn' : 'btn btn--primary nx-install__btn'}
              onClick={copy} aria-label={state === 'idle' ? `Copy ${label}` : undefined}>
        {shown}
      </button>
      <p className="visually-hidden" role="status">
        {state === 'copied' ? `${capitalised(label)} copied.` : state === 'failed' ? 'Copy failed: the text is selected, press Ctrl+C.' : ''}
      </p>
    </div>
  )
}

function capitalised(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}
