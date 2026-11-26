import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

interface AppState {
  /** Replay date (YYYY-MM-DD) or null for the latest data. */
  asOf: string | null
  setAsOf: (d: string | null) => void
  provenance: { open: boolean; runId: string | null }
  openProvenance: (runId?: string | null) => void
  closeProvenance: () => void
}

const Ctx = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [asOf, setAsOf] = useState<string | null>(null)
  const [provenance, setProv] = useState<{ open: boolean; runId: string | null }>({ open: false, runId: null })
  const openProvenance = useCallback((runId?: string | null) => setProv({ open: true, runId: runId ?? null }), [])
  const closeProvenance = useCallback(() => setProv((p) => ({ ...p, open: false })), [])
  const value = useMemo(
    () => ({ asOf, setAsOf, provenance, openProvenance, closeProvenance }),
    [asOf, provenance, openProvenance, closeProvenance],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp(): AppState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp must be used inside AppProvider')
  return v
}
