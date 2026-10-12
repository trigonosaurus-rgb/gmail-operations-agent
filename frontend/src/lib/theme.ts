import { useCallback, useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

// public/theme.js sets the first value before React loads; this keeps it in sync.
const root = document.documentElement
const listeners = new Set<() => void>()

function current(): Theme {
  return root.classList.contains('dark') ? 'dark' : 'light'
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const theme = useSyncExternalStore((listener) => {
    listeners.add(listener)
    return () => listeners.delete(listener)
  }, current)
  const set = useCallback((next: Theme) => {
    root.classList.toggle('dark', next === 'dark')
    try {
      localStorage.setItem('theme', next)
    } catch {
      // private mode: the choice lasts until reload
    }
    for (const listener of listeners) listener()
  }, [])
  return [theme, set]
}
