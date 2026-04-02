import type { Config } from 'tailwindcss'
import scrollbar from 'tailwind-scrollbar'

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: 'var(--color-primary)',
        secondary: 'var(--color-secondary)',
        accent: 'var(--color-accent)',
        background: 'var(--color-background)',
        foreground: 'var(--color-foreground)',
        card: 'var(--color-card)',
        'card-fg': 'var(--color-card-fg)',
        muted: 'var(--color-muted)',
        'muted-fg': 'var(--color-muted-fg)',
        border: 'var(--color-border)',
        destructive: 'var(--color-destructive)',
        cta: 'var(--color-cta)',
        success: 'var(--color-success)',
        warning: 'var(--color-warning)',
        error: 'var(--color-error)',
        info: 'var(--color-info)',
      },
      fontFamily: { sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'] },
      borderRadius: { card: '12px', btn: '8px', input: '8px' },
      boxShadow: {
        card: 'var(--shadow-card)',
        'card-hover': 'var(--shadow-card-hover)',
        'glow-accent': 'var(--shadow-glow-accent)',
        'glow-cta': 'var(--shadow-glow-cta)',
      },
    },
  },
  plugins: [scrollbar],
} satisfies Config
