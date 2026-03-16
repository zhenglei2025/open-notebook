import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '@/lib/api/client'
import { NotePptTask } from '@/lib/types/api'

export const PPT_QUERY_KEY = 'ppt-tasks'

export function usePptTasks(noteId?: string) {
    return useQuery<NotePptTask[]>({
        queryKey: [PPT_QUERY_KEY, noteId],
        queryFn: async () => {
            const res = await apiClient.get<NotePptTask[]>(`/notes/${noteId}/ppt-tasks`)
            return res.data
        },
        enabled: !!noteId,
        staleTime: 30_000, // show cached data instantly, refetch in background
        refetchInterval: (query) => {
            // Poll every 3s while any task is still running
            const data = query.state.data
            if (data?.some(t => t.status === 'queued' || t.status === 'running')) {
                return 3000
            }
            return false
        },
    })
}

export function useGeneratePpt() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async ({ noteId, userPrompt }: { noteId: string; userPrompt?: string }) => {
            const res = await apiClient.post<NotePptTask>(`/notes/${noteId}/generate-ppt`, {
                user_prompt: userPrompt || null,
            })
            return res.data
        },
        onSuccess: (data) => {
            // Immediately add the new task to the query cache so it shows up instantly
            // Polling (refetchInterval) will sync with server automatically
            queryClient.setQueryData<NotePptTask[]>(
                [PPT_QUERY_KEY, data.note],
                (old) => [...(old || []), data]
            )
        },
    })
}

export function useDeletePpt() {
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: async (pptId: string) => {
            await apiClient.delete(`/notes/ppt/${pptId}`)
            return pptId
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: [PPT_QUERY_KEY] })
        },
    })
}

export async function downloadPpt(pptId: string) {
    const res = await apiClient.get(`/notes/ppt/${pptId}/download`, {
        responseType: 'blob',
    })
    const blob = new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    })
    const url = URL.createObjectURL(blob)

    // Extract filename from Content-Disposition (handles UTF-8 filename*)
    const disposition = res.headers['content-disposition']
    let filename = 'presentation.pptx'
    if (disposition) {
        const utf8Match = disposition.match(/filename\*=UTF-8''(.+?)(?:;|$)/i)
        if (utf8Match) {
            filename = decodeURIComponent(utf8Match[1])
        } else {
            const match = disposition.match(/filename="?(.+?)"?(?:;|$)/i)
            if (match) filename = match[1]
        }
    }

    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
}
