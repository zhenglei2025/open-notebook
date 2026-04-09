import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { buildApiEndpoint, getApiUrl } from '@/lib/config'

interface AuthState {
  isAuthenticated: boolean
  token: string | null
  username: string | null
  isAdmin: boolean
  isLoading: boolean
  error: string | null
  lastAuthCheck: number | null
  isCheckingAuth: boolean
  hasHydrated: boolean
  authRequired: boolean | null
  setHasHydrated: (state: boolean) => void
  checkAuthRequired: () => Promise<boolean>
  login: (username: string, password: string) => Promise<boolean>
  logout: () => void
  checkAuth: () => Promise<boolean>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      isAuthenticated: false,
      token: null,
      username: null,
      isAdmin: false,
      isLoading: false,
      error: null,
      lastAuthCheck: null,
      isCheckingAuth: false,
      hasHydrated: false,
      authRequired: null,

      setHasHydrated: (state: boolean) => {
        set({ hasHydrated: state })
      },

      checkAuthRequired: async () => {
        try {
          const apiUrl = await getApiUrl()
          const response = await fetch(buildApiEndpoint(apiUrl, '/api/auth/status'), {
            cache: 'no-store',
          })

          if (!response.ok) {
            throw new Error(`Auth status check failed: ${response.status}`)
          }

          const data = await response.json()
          const required = data.auth_enabled || false
          set({ authRequired: required })

          // If auth is not required, mark as authenticated
          if (!required) {
            set({ isAuthenticated: true, token: 'not-required' })
          }

          return required
        } catch (error) {
          console.error('Failed to check auth status:', error)

          // If it's a network error, set a more helpful error message
          if (error instanceof TypeError && error.message.includes('Failed to fetch')) {
            set({
              error: 'Unable to connect to server. Please check if the API is running.',
              authRequired: null  // Don't assume auth is required if we can't connect
            })
          } else {
            // For other errors, default to requiring auth to be safe
            set({ authRequired: true })
          }

          // Re-throw the error so the UI can handle it
          throw error
        }
      },

      login: async (username: string, password: string) => {
        set({ isLoading: true, error: null })
        try {
          const apiUrl = await getApiUrl()

          // Call the login endpoint
          const response = await fetch(buildApiEndpoint(apiUrl, '/api/auth/login'), {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
          })

          if (response.ok) {
            const data = await response.json()
            set({
              isAuthenticated: true,
              token: data.token,
              username: data.username,
              isAdmin: data.is_admin || false,
              isLoading: false,
              lastAuthCheck: Date.now(),
              error: null
            })
            return true
          } else {
            let errorMessage = 'Authentication failed'
            if (response.status === 401) {
              errorMessage = 'Invalid username or password. Please try again.'
            } else if (response.status === 403) {
              errorMessage = 'Access denied. Please check your credentials.'
            } else if (response.status >= 500) {
              errorMessage = 'Server error. Please try again later.'
            } else {
              errorMessage = `Authentication failed (${response.status})`
            }

            set({
              error: errorMessage,
              isLoading: false,
              isAuthenticated: false,
              token: null,
              username: null,
              isAdmin: false
            })
            return false
          }
        } catch (error) {
          console.error('Network error during auth:', error)
          let errorMessage = 'Authentication failed'

          if (error instanceof TypeError && error.message.includes('Failed to fetch')) {
            errorMessage = 'Unable to connect to server. Please check if the API is running.'
          } else if (error instanceof Error) {
            errorMessage = `Network error: ${error.message}`
          } else {
            errorMessage = 'An unexpected error occurred during authentication'
          }

          set({
            error: errorMessage,
            isLoading: false,
            isAuthenticated: false,
            token: null,
            username: null,
            isAdmin: false
          })
          return false
        }
      },

      logout: () => {
        set({
          isAuthenticated: false,
          token: null,
          username: null,
          isAdmin: false,
          error: null,
          lastAuthCheck: null,
        })
        // Fully remove persisted auth data from localStorage
        if (typeof window !== 'undefined') {
          localStorage.removeItem('auth-storage')
        }
      },

      checkAuth: async () => {
        const state = get()
        const { token, lastAuthCheck, isCheckingAuth, isAuthenticated } = state

        // If already checking, return current auth state
        if (isCheckingAuth) {
          return isAuthenticated
        }

        // If no token, not authenticated
        if (!token) {
          return false
        }

        // If we checked recently (within 30 seconds) and are authenticated, skip
        const now = Date.now()
        if (isAuthenticated && lastAuthCheck && (now - lastAuthCheck) < 30000) {
          return true
        }

        set({ isCheckingAuth: true })

        try {
          const apiUrl = await getApiUrl()

          const response = await fetch(buildApiEndpoint(apiUrl, '/api/notebooks'), {
            method: 'GET',
            headers: {
              'Authorization': `Bearer ${token}`,
              'Content-Type': 'application/json'
            }
          })

          if (response.ok) {
            set({
              isAuthenticated: true,
              lastAuthCheck: now,
              isCheckingAuth: false
            })
            return true
          } else {
            set({
              isAuthenticated: false,
              token: null,
              username: null,
              isAdmin: false,
              lastAuthCheck: null,
              isCheckingAuth: false
            })
            return false
          }
        } catch (error) {
          console.error('checkAuth error:', error)
          set({
            isAuthenticated: false,
            token: null,
            username: null,
            isAdmin: false,
            lastAuthCheck: null,
            isCheckingAuth: false
          })
          return false
        }
      }
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        token: state.token,
        isAuthenticated: state.isAuthenticated,
        username: state.username,
        isAdmin: state.isAdmin
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      }
    }
  )
)
