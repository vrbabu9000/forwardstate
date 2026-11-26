import { useEffect, useState } from 'react'

/** Bumps when the light/dark theme changes, so canvas charts can re-read CSS variables. */
export function useThemeVersion(): number {
  const [v, setV] = useState(0)
  useEffect(() => {
    const bump = () => setV((x) => x + 1)
    const mo = new MutationObserver(bump)
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    mq?.addEventListener?.('change', bump)
    return () => {
      mo.disconnect()
      mq?.removeEventListener?.('change', bump)
    }
  }, [])
  return v
}
