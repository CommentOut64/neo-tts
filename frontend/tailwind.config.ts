import type { Config } from 'tailwindcss'
import scrollbar from 'tailwind-scrollbar'

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: '#1E293B', secondary: '#334155', accent: '#22C55E',
        background: '#0F172A', foreground: '#F8FAFC', card: '#1B2336',
        'card-fg': '#F8FAFC', muted: '#272F42', 'muted-fg': '#94A3B8',
        border: '#475569', destructive: '#EF4444', cta: '#3B82F6',
        success: '#22C55E', warning: '#F59E0B', error: '#EF4444', info: '#3B82F6',
      },
      fontFamily: { sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'] },
      borderRadius: { card: '12px', btn: '8px', input: '8px' },
      boxShadow: {
        card: '0 2px 8px rgba(0, 0, 0, 0.3)',
        'card-hover': '0 4px 16px rgba(0, 0, 0, 0.4)',
        'glow-accent': '0 0 12px rgba(34, 197, 94, 0.25)',
        'glow-cta': '0 0 12px rgba(59, 130, 246, 0.25)',
      },
    },
  },
  plugins: [scrollbar],
} satisfies Config
