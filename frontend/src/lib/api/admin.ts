import { apiClient } from './client'
import { FeedbackItem } from './feedback'

export interface User {
  username: string
  db_name: string
  is_admin: boolean
  created?: string
  source_count?: number
  note_count?: number
  ppt_count?: number
  quick_research_count?: number
  deep_research_count?: number
}

export interface CreateUserRequest {
  username: string
  password: string
  is_admin: boolean
}

export interface RunningStats {
  running_research: number
}

export const adminApi = {
  listUsers: async (): Promise<{ users: User[]; running_stats: RunningStats }> => {
    const response = await apiClient.get('/admin/users')
    return { users: response.data.users, running_stats: response.data.running_stats }
  },

  createUser: async (data: CreateUserRequest): Promise<{ message: string; user: User }> => {
    const response = await apiClient.post('/admin/users', data)
    return response.data
  },

  deleteUser: async (username: string): Promise<{ message: string }> => {
    const response = await apiClient.delete(`/admin/users/${username}`)
    return response.data
  },

  listFeedback: async (): Promise<{ feedback: FeedbackItem[] }> => {
    const response = await apiClient.get('/admin/feedback')
    return response.data
  },
}
