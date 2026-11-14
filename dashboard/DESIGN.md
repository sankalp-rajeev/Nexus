# Design

The Nexus demo page's visual system, recorded from the built page (`src/hero/`, `src/story/`). Theme: Hallmark
**Console**, graphite colourway. The replay explorer (`src/replay/`) uses the same tokens through Tailwind colour
names (`text-ink`, `bg-paper2`, `border-rule`, ...) defined in `tailwind.config.js`; the live dashboard (`App.tsx`)
keeps its own light Tailwind styles and tokens in `src/index.css`.

## Page order

Hero; the problem (rows); what Nexus does (the story diagram, horizontal on wide screens and vertical below 1024px, with the verification job as the one amber element; then a six-stage flow, the three checks outlined in cool; a link to the full architecture diagram); the finding (an
index of readings with interval and source); per class and dev-vs-test (bar charts on a band); one heal step by step
(vertical tabs beside an audit trail); cost (five figures on a band); use it (copyable
code); limits (rows); the recorded evidence (the replay explorer behind a disclosure); a colophon footer.

## World

An instrument kept by careful people. Graphite ground in three lightness steps, hairline panels cut from one
surface, a grotesk for what a person reads, a mono for what was measured. Nothing glows. Not a neon terminal,
not a glass dashboard.

## Tokens (`src/hero/tokens.css`)

- **Paper:** `--color-paper` oklch(17% 0.008 250), `--color-paper-2` 21% (panels), `--color-paper-3` 13.5% (code wells).
- **Ink:** `--color-ink` 95%, `--color-ink-2` 83% (lede, labels on the lead), `--color-muted` 71% (labels).
- **Rules:** `--color-rule` 31% (seams), `--color-rule-2` 42% (underlines, selected edges).
- **Meaning:** amber `--color-accent` = a person or the one primary control (the Copy button, focus rings, hover);
  cool `--color-cool` = an instrument reading (the 95% interval); `--color-bad` / `--color-ok` only for status
  (the broken share of the proportion bar). Never swap amber and cool.
- **Type:** `--font-display`/`--font-body` Host Grotesk 400 and 500; `--font-outlier` Atkinson Hyperlegible Mono
  400 for measured values, commands and file:line citations only, never labels or headings. Self-hosted via
  `@fontsource` (the replay build is offline).
- **Scale:** the Hallmark scale in `tokens.css` (`--text-*`, `--space-*`, `--dur-*`, `--ease-*`). Radii: 10px panels,
  6px controls.

## Components

- **Proof panel:** one `<figure>` with 1px seams (`gap: 1px` on a `--color-rule` ground). Header row with the scope,
  a lead reading set large in the mono (k/n, the `/n` muted, read as "k of n"), then rows of reading beside label
  and source link. Every number comes from `replay.json` (`headline.hero.proof`); words for numbers (“a third”)
  are computed from exact ratios in `src/hero/numbers.ts`.
- **Source link:** mono `file:line`, lands on the committed row at the exported commit (`?plain=1#L<n>` for Markdown).
- **Controls:** the pair: amber fill (`--color-accent-ink` text) beside a `--color-muted` outline on paper-2, 48px
  tall, 6px radius. One filled control per page. Text links underline in `--color-rule-2`, turn amber on hover.
  Focus: 2px amber outline, offset 2px, instant.
- **Charts:** horizontal bars from the baseline, 4px data ends, the 95% interval as a 2px ink line, every bar
  direct-labelled with k/n and the interval. Two series tokens, `--color-series-a` (LLM critic) and
  `--color-series-b` (generic template), validated with the dataviz palette check against paper-2 (all pass).
- **Walkthrough:** a vertical tab list (arrow keys, Home, End) beside an audit trail on a 1px spine; ok and bad
  dots and status chips carry the check outcomes, always with the word.
- **Section boundary:** a missing number hides its section with a plain notice; the rest of the page renders.
- **Install command:** a paper-3 well holding the mono command with the Copy button attached; real clipboard
  write, visible "Copied" or "Press Ctrl+C" state and a `role="status"` message.

## Rules

- Evidence first: each figure carries its scope (DEV or TEST), denominator and source.
- No photographs or decorative imagery; visuals are type, numbers, diagrams and the recorded heals.
- No eyebrows, no tracked capitals, no middle-dot meta strings, no gradients, no shadows.
- WCAG AA contrast, visible focus on every control, reduced motion respected, no horizontal scroll at 390px.
- Hallmark stamp heads `src/hero/hero.css`; run `sloplint` after changes.
