import './index.css'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { ApiError, api } from '@/api/client'
import { keys } from '@/api/queries'
import type { StatusOut } from '@/api/types'
import { router } from '@/router'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // The event stream keeps data fresh; refetching on focus would only add load.
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (failures, error) =>
        failures < 2 && !(error instanceof ApiError && error.status < 500),
    },
  },
})

// One request first: in the demo, the first answer sets the visitor's sandbox cookie.
// Requests fired in parallel without it would each get a sandbox of their own.
try {
  queryClient.setQueryData(keys.status, await api<StatusOut>('/api/status'))
} catch {
  // the app renders and shows the error where the data is missing
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
