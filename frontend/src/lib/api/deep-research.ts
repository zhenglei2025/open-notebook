/**
 * Deep Research API client.
 * Uses polling for background job status.
 */

import apiClient from './client'

export interface DeepResearchEvent {
    type: 'outline' | 'search_done' | 'evaluate' | 'write_done' | 'summarize_done' | 'compiling' | 'complete' | 'report' | 'error' | 'done'
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

export interface DeepResearchJobResponse {
    job_id: string
    status: string
    question: string
}

export interface DeepResearchStatusResponse {
    job_id: string
    status: string
    question: string
    events: DeepResearchEvent[]
    final_report: string | null
    error: string | null
}

/**
 * Start a deep research job (returns immediately with job_id).
 */
export async function startDeepResearch(
    question: string,
    notebookId?: string,
    modelId?: string,
    sessionId?: string,
    researchType: string = 'deep',
): Promise<DeepResearchJobResponse> {
    const response = await apiClient.post<DeepResearchJobResponse>('/deep-research', {
        question,
        notebook_id: notebookId || null,
        model_id: modelId || null,
        session_id: sessionId || null,
        research_type: researchType,
    })
    return response.data
}

/**
 * Get the current status and events of a deep research job.
 * Uses events_after cursor so only new events are returned.
 */
export async function getDeepResearchStatus(
    jobId: string,
    eventsAfter: number = 0,
): Promise<DeepResearchStatusResponse> {
    const response = await apiClient.get<DeepResearchStatusResponse>(
        `/deep-research/${encodeURIComponent(jobId)}`,
        { params: { events_after: eventsAfter } },
    )
    return response.data
}

/**
 * Get the most recent deep research job for a notebook (if any).
 * Used to resume display when navigating back.
 */
export async function getActiveDeepResearch(
    notebookId: string,
    sessionId?: string,
): Promise<DeepResearchStatusResponse | null> {
    try {
        const params: Record<string, string> = {}
        if (sessionId) params.session_id = sessionId
        const response = await apiClient.get<DeepResearchStatusResponse | null>(
            `/deep-research/active/${encodeURIComponent(notebookId)}`,
            { params },
        )
        return response.data
    } catch {
        return null
    }
}

/**
 * Cancel a running deep research job.
 */
export async function cancelDeepResearch(jobId: string): Promise<void> {
    await apiClient.post(`/deep-research/${encodeURIComponent(jobId)}/cancel`)
}
