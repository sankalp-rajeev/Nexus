// Words that stand for numbers are computed here from replay.json values, never typed into copy.
import type { Count, HeroComparison, HeroFraction, HeroProof, ReplayData, StoryFigure } from '../replay'

const SMALL = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']

/** "four" for 4; digits past ten. */
export function word(n: number): string {
  return Number.isInteger(n) && n >= 0 && n <= 10 ? SMALL[n] : String(n)
}

/**
 * "one in four" for 12/48; "12 of 48" when n is not a whole multiple of k.
 * Only an exact ratio gets words, so the phrase never rounds a number the reader cannot see.
 */
export function oneIn(k: number, n: number): string {
  if (k > 0 && n % k === 0 && n / k <= 10) return `one in ${word(n / k)}`
  return `${k} of ${n}`
}

export function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Recall-style values: three decimals. */
export function decimal(value: number, places = 3): string {
  return value.toFixed(places)
}

/** A 95% interval as percentages: "20% to 50%" (no dashes in running copy). */
export function interval([low, high]: [number, number]): string {
  return `${Math.round(low * 100)}% to ${Math.round(high * 100)}%`
}

/** "p50 0.01 s": seconds with sensible precision. */
export function secondsText(value: number): string {
  if (value >= 60) return `${Math.round(value / 6) / 10} min`
  return `${value < 1 ? value.toFixed(2) : value.toFixed(1)} s`
}

export function usd(value: number): string {
  return `$${value.toFixed(3)}`
}

/** GitHub link to the cited line at the exported commit; Markdown needs ?plain=1 for line anchors. */
export function citeUrl(data: ReplayData, cite: { path: string; line: number }): string {
  const plain = cite.path.endsWith('.md') ? '?plain=1' : ''
  return `${data.provenance.repository}/blob/${data.provenance.generated_from_commit}/${cite.path}${plain}#L${cite.line}`
}

/** A file in the repository on its default branch (docs, licence). */
export function repoFile(data: ReplayData, path: string): string {
  return `${data.provenance.repository}/blob/main/${path}`
}

export function proof(data: ReplayData, id: string, kind: 'fraction'): HeroFraction
export function proof(data: ReplayData, id: string, kind: 'comparison'): HeroComparison
export function proof(data: ReplayData, id: string, kind: HeroProof['kind']): HeroProof {
  const found = data.headline.hero?.proof.find(item => item.id === id)
  if (!found || found.kind !== kind) throw new Error(`replay.json has no ${kind} hero number "${id}"`)
  return found
}

export function figure(data: ReplayData, id: string): StoryFigure {
  const found = data.headline.story?.figures.find(item => item.id === id)
  if (!found) throw new Error(`replay.json has no story figure "${id}"`)
  return found
}

/** A named arm of a versus figure (critic, generic, dev, ...). */
export function arm(item: StoryFigure, name: 'critic' | 'generic' | 'no_patch' | 'dev' | 'test'): Count {
  const found = item[name]
  if (!found) throw new Error(`story figure "${item.id}" has no ${name} arm`)
  return found
}

export function value(item: StoryFigure, key: string): number {
  const found = item.values?.[key]
  if (found === undefined || found === null) throw new Error(`story figure "${item.id}" has no value "${key}"`)
  return found
}

/** The file name a source link shows, e.g. "test_scoring.md". */
export function fileName(path: string): string {
  return path.split('/').pop() ?? path
}
