import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { api } from './client'
import {
  FILTER_STATES,
  type ApproveIn,
  type DemoOut,
  type Filter,
  type MessageDetail,
  type MessagePage,
  type StatsOut,
  type StatusOut,
  type TestEmailIn,
  type TestEmailOut,
} from './types'

export const keys = {
  messages: ['messages'] as const,
  list: (filter: Filter, q: string) => ['messages', filter, q] as const,
  message: (id: string) => ['message', id] as const,
  status: ['status'] as const,
  stats: (hours: number) => ['stats', hours] as const,
  demo: ['demo'] as const,
}

export function useMessages(filter: Filter, q: string) {
  return useInfiniteQuery({
    queryKey: keys.list(filter, q),
    queryFn: ({ pageParam, signal }) =>
      api<MessagePage>('/api/messages', {
        query: { state: FILTER_STATES[filter], q, before: pageParam },
        signal,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_before ?? undefined,
    placeholderData: keepPreviousData, // typing in search keeps the old rows until new ones arrive
  })
}

export function useMessage(id: string | undefined) {
  return useQuery({
    queryKey: keys.message(id ?? ''),
    queryFn: ({ signal }) => api<MessageDetail>(`/api/messages/${encodeURIComponent(id!)}`, { signal }),
    enabled: !!id,
  })
}

export function useStatus() {
  return useQuery({
    queryKey: keys.status,
    queryFn: ({ signal }) => api<StatusOut>('/api/status', { signal }),
    refetchInterval: 15_000, // worker health is not part of the event stream
  })
}

export function useStats(hours: number) {
  return useQuery({
    queryKey: keys.stats(hours),
    queryFn: ({ signal }) => api<StatsOut>('/api/stats', { query: { hours }, signal }),
    placeholderData: keepPreviousData,
  })
}

export function useDemo(enabled: boolean) {
  return useQuery({
    queryKey: keys.demo,
    queryFn: ({ signal }) => api<DemoOut>('/api/demo', { signal }),
    enabled,
    staleTime: 60_000,
  })
}

/** Approve, reject or retry: the answer is the updated message, so the card updates at once. */
export function useDecision(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ action, body }: { action: 'approve' | 'reject' | 'retry'; body?: ApproveIn }) =>
      api<MessageDetail>(`/api/messages/${encodeURIComponent(id)}/${action}`, {
        method: 'POST',
        body,
      }),
    onSuccess: (detail) => {
      client.setQueryData(keys.message(id), detail)
      void client.invalidateQueries({ queryKey: keys.messages })
    },
  })
}

export function useSetMode() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (mode: StatusOut['mode']) =>
      api<StatusOut>('/api/settings', { method: 'PUT', body: { mode } }),
    onSuccess: (status) => client.setQueryData(keys.status, status),
  })
}

export function useSendTestEmail() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: TestEmailIn) =>
      api<TestEmailOut>('/api/demo/emails', { method: 'POST', body }),
    onSuccess: (result) => {
      client.setQueryData<DemoOut>(keys.demo, (demo) => demo && { ...demo, quota: result.quota })
      void client.invalidateQueries({ queryKey: keys.messages })
    },
  })
}

export function useResetDemo(onReset: () => void) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<StatusOut>('/api/demo/reset', { method: 'POST' }),
    onSuccess: () => {
      client.clear() // a new sandbox: nothing cached belongs to it
      onReset()
    },
  })
}
