import { createContext, useContext } from 'react'

/** Bumped after a demo reset: the event stream reconnects for the new sandbox. */
export const SessionContext = createContext<{ session: number; restart: () => void }>({
  session: 0,
  restart: () => {},
})

export function useSession() {
  return useContext(SessionContext)
}
