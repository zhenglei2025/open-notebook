import apiClient from './client'
import { ImportJobResponse } from '@/lib/types/api'

export const importsApi = {
  create: async (params: {
    files: File[]
    notebooks?: string[]
    transformations?: string[]
    embed?: boolean
    delete_source?: boolean
  }) => {
    const formData = new FormData()

    params.files.forEach((file) => {
      formData.append('files', file)
    })

    if (params.notebooks) {
      formData.append('notebooks', JSON.stringify(params.notebooks))
    }
    if (params.transformations) {
      formData.append('transformations', JSON.stringify(params.transformations))
    }

    formData.append('embed', String(params.embed ?? false))
    formData.append('delete_source', String(params.delete_source ?? false))

    const response = await apiClient.post<ImportJobResponse>('/imports', formData)
    return response.data
  },

  get: async (id: string) => {
    const response = await apiClient.get<ImportJobResponse>(`/imports/${id}`)
    return response.data
  },
}
