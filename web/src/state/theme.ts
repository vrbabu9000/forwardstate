import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

function systemTheme(): Theme {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function storedTheme(): Theme | null {
  try {
    const t = localStorage.getItem('fs-theme')
    return t === 'light' || t === 'dark' ? t : null
  } catch {
    return null
  }
}

/** Effective theme: an explicit choice wins, else the OS setting. */
export function useTheme() {
  const [choice, setChoice] = useState<Theme | null>(storedTheme)
  const [system, setSystem] = useState<Theme>(systemTheme)
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const on = () => setSystem(mq.matches ? 'dark' : 'light')
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [])
  const theme = choice ?? system
  useEffect(() => {
    if (choice) document.documentElement.dataset.theme = choice
    else delete document.documentElement.dataset.theme
    try {
      if (choice) localStorage.setItem('fs-theme', choice)
      else localStorage.removeItem('fs-theme')
    } catch {
      /* storage blocked */
    }
  }, [choice])
  return { theme, toggle: () => setChoice(theme === 'dark' ? 'light' : 'dark') }
}

/** Read a CSS custom property (for canvas charts that cannot use var()). */
export function cssVar(name: string, fallback = '#888'): string {
  if (typeof window === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}
