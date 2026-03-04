/**
 * Deep Research API client.
 * Uses SSE (Server-Sent Events) for streaming progress.
 */

import { getApiUrl } from '@/lib/config'

export interface DeepResearchEvent {
    type: 'outline' | 'search_done' | 'evaluate' | 'write_done' | 'summarize_done' | 'complete' | 'report' | 'error' | 'done'
    // outline
    sections?: { title: string; description: string }[]
    reasoning?: string
    // search_done
    section?: string
    section_index?: number
    attempt?: number
    new_results?: number
    total_results?: number
    // evaluate
    sufficient?: boolean
    reason?: string
    relevant_count?: number
    total_count?: number
    new_queries?: string[]
    // write_done
    draft_length?: number
    preview?: string
    // summarize_done
    summary?: string
    // report
    content?: string
    report_length?: number
    // error
    message?: string
}

export async function startDeepResearch(
    question: string,
    modelId?: string,
    onEvent?: (event: DeepResearchEvent) => void,
): Promise<string> {
    const apiUrl = await getApiUrl()
    const url = `${apiUrl}/api/deep-research`

    // Get auth token
    let token = ''
    if (typeof window !== 'undefined') {
        const authStorage = localStorage.getItem('auth-storage')
        if (authStorage) {
            try {
                const { state } = JSON.parse(authStorage)
                if (state?.token) token = state.token
            } catch { /* ignore */ }
        }
    }

    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ question, model_id: modelId || null }),
    })

    if (!response.ok) {
        throw new Error(`Deep research failed: ${response.statusText}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('No response body')

    const decoder = new TextDecoder()
    let finalReport = ''
    let buffer = ''

    while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE events from buffer
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // Keep incomplete line in buffer

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                try {
                    const event: DeepResearchEvent = JSON.parse(line.slice(6))
                    onEvent?.(event)

                    if (event.type === 'report' && event.content) {
                        finalReport = event.content
                    }
                    if (event.type === 'error') {
                        throw new Error(event.message || 'Deep research failed')
                    }
                } catch (e) {
                    if (e instanceof Error && e.message !== 'Deep research failed') {
                        console.warn('Failed to parse SSE event:', line, e)
                    } else {
                        throw e
                    }
                }
            }
        }
    }

    return finalReport
}
