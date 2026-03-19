import { apiClient } from './client'

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

export const adminApi = {
  listUsers: async (): Promise<User[]> => {
    const response = await apiClient.get('/admin/users')
    return response.data.users
  },

  createUser: async (data: CreateUserRequest): Promise<{ message: string; user: User }> => {
    const response = await apiClient.post('/admin/users', data)
    return response.data
  },

  deleteUser: async (username: string): Promise<{ message: string }> => {
    const response = await apiClient.delete(`/admin/users/${username}`)
    return response.data
  },
}
