import { useMutation, useQuery } from '@tanstack/react-query'

import { importsApi } from '@/lib/api/imports'
import { QUERY_KEYS } from '@/lib/api/query-client'

const TERMINAL_STATUSES = new Set(['completed', 'partial_failed', 'failed'])

export function useCreateImportJob() {
  return useMutation({
    mutationFn: importsApi.create,
  })
}

export function useImportJob(importJobId: string | null, enabled = true) {
  return useQuery({
    queryKey: importJobId ? QUERY_KEYS.importJob(importJobId) : ['imports', 'idle'],
    queryFn: () => importsApi.get(importJobId as string),
    enabled: enabled && !!importJobId,
    staleTime: 0,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (!status || TERMINAL_STATUSES.has(status)) {
        return false
      }
      return 2000
    },
  })
}
