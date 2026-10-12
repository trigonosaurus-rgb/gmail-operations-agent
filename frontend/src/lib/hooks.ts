import { useSyncExternalStore } from 'react'

/** Matches the `lg` breakpoint: the list and the email side by side. */
export const WIDE = '(min-width: 64rem)'

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (listener) => {
      const list = matchMedia(query)
      list.addEventListener('change', listener)
      return () => list.removeEventListener('change', listener)
    },
    () => matchMedia(query).matches,
  )
}
