/** @type {import('tailwindcss').Config} */
// Fonts and the theme colours resolve through CSS tokens: src/index.css sets the live dashboard's,
// src/hero/tokens.css the replay page's (Console theme). Stone stays for the live dashboard.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-body)'],
        mono: ['var(--font-outlier)'],
      },
      colors: {
        stone: {
          925: '#111110',
          950: '#0c0c0b',
        },
        paper: 'var(--color-paper)',
        paper2: 'var(--color-paper-2)',
        paper3: 'var(--color-paper-3)',
        ink: 'var(--color-ink)',
        ink2: 'var(--color-ink-2)',
        muted: 'var(--color-muted)',
        rule: 'var(--color-rule)',
        rule2: 'var(--color-rule-2)',
        accent: 'var(--color-accent)',
        accentsoft: 'var(--color-accent-soft)',
        cool: 'var(--color-cool)',
        coolsoft: 'var(--color-cool-soft)',
        ok: 'var(--color-ok)',
        oksoft: 'var(--color-ok-soft)',
        bad: 'var(--color-bad)',
        badsoft: 'var(--color-bad-soft)',
      },
    },
  },
  plugins: [],
}
