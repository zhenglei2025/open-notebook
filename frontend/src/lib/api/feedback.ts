import { apiClient } from './client'

export type FeedbackCategory = 'feature' | 'bug'

export interface FeedbackItem {
  id: string
  username: string
  category: FeedbackCategory
  title: string
  description: string
  status: string
  created: string
}

export interface CreateFeedbackRequest {
  category: FeedbackCategory
  title: string
  description: string
}

export const feedbackApi = {
  create: async (data: CreateFeedbackRequest): Promise<{ message: string; feedback: FeedbackItem }> => {
    const response = await apiClient.post('/feedback', data)
    return response.data
  },

  listAdmin: async (): Promise<{ feedback: FeedbackItem[] }> => {
    const response = await apiClient.get('/admin/feedback')
    return response.data
  },
}
