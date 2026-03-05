'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/hooks/use-auth'
import { useAuthStore } from '@/lib/stores/auth-store'
import { getConfig } from '@/lib/config'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { AlertCircle, KeyRound, CheckCircle2 } from 'lucide-react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useTranslation } from '@/lib/hooks/use-translation'
import apiClient from '@/lib/api/client'

export function LoginForm() {
  const { t, language } = useTranslation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const { login, isLoading, error } = useAuth()
  const { authRequired, checkAuthRequired, hasHydrated, isAuthenticated } = useAuthStore()
  const [isCheckingAuth, setIsCheckingAuth] = useState(true)
  const [configInfo, setConfigInfo] = useState<{ apiUrl: string; version: string; buildTime: string } | null>(null)
  const router = useRouter()

  // Change password state
  const [changePasswordOpen, setChangePasswordOpen] = useState(false)
  const [cpUsername, setCpUsername] = useState('')
  const [cpCurrentPassword, setCpCurrentPassword] = useState('')
  const [cpNewPassword, setCpNewPassword] = useState('')
  const [cpConfirmPassword, setCpConfirmPassword] = useState('')
  const [cpLoading, setCpLoading] = useState(false)
  const [cpError, setCpError] = useState<string | null>(null)
  const [cpSuccess, setCpSuccess] = useState(false)

  // Load config info for debugging
  useEffect(() => {
    getConfig().then(cfg => {
      setConfigInfo({
        apiUrl: cfg.apiUrl,
        version: cfg.version,
        buildTime: cfg.buildTime,
      })
    }).catch(err => {
      console.error('Failed to load config:', err)
    })
  }, [])

  // Check if authentication is required on mount
  useEffect(() => {
    if (!hasHydrated) {
      return
    }

    const checkAuth = async () => {
      try {
        const required = await checkAuthRequired()

        // If auth is not required, redirect to notebooks
        if (!required) {
          router.push('/notebooks')
        }
      } catch (error) {
        console.error('Error checking auth requirement:', error)
        // On error, assume auth is required to be safe
      } finally {
        setIsCheckingAuth(false)
      }
    }

    // If we already know auth status, use it
    if (authRequired !== null) {
      if (!authRequired && isAuthenticated) {
        router.push('/notebooks')
      } else {
        setIsCheckingAuth(false)
      }
    } else {
      void checkAuth()
    }
  }, [hasHydrated, authRequired, checkAuthRequired, router, isAuthenticated])

  // Show loading while checking if auth is required
  if (!hasHydrated || isCheckingAuth) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <LoadingSpinner />
      </div>
    )
  }

  // If we still don't know if auth is required (connection error), show error
  if (authRequired === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle>{t.common.connectionError}</CardTitle>
            <CardDescription>
              {t.common.unableToConnect}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-start gap-2 text-red-600 text-sm">
                <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                <div className="flex-1">
                  {error || t.auth.connectErrorHint}
                </div>
              </div>

              {configInfo && (
                <div className="space-y-2 text-xs text-muted-foreground border-t pt-3">
                  <div className="font-medium">{t.common.diagnosticInfo}:</div>
                  <div className="space-y-1 font-mono">
                    <div>{t.common.version}: {configInfo.version}</div>
                    <div>{t.common.built}: {new Date(configInfo.buildTime).toLocaleString(language === 'zh-CN' ? 'zh-CN' : language === 'zh-TW' ? 'zh-TW' : 'en-US')}</div>
                    <div className="break-all">{t.common.apiUrl}: {configInfo.apiUrl}</div>
                    <div className="break-all">{t.common.frontendUrl}: {typeof window !== 'undefined' ? window.location.href : 'N/A'}</div>
                  </div>
                  <div className="text-xs pt-2">
                    {t.common.checkConsoleLogs}
                  </div>
                </div>
              )}

              <Button
                onClick={() => window.location.reload()}
                className="w-full"
              >
                {t.common.retryConnection}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (username.trim() && password.trim()) {
      try {
        await login(username, password)
      } catch (error) {
        console.error('Unhandled error during login:', error)
        // The auth store should handle most errors, but this catches any unhandled ones
      }
    }
  }

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setCpError(null)
    setCpSuccess(false)

    // Validate passwords match
    if (cpNewPassword !== cpConfirmPassword) {
      setCpError(t.auth.passwordMismatch)
      return
    }

    if (!cpNewPassword.trim()) {
      setCpError(t.auth.passwordChangeFailed)
      return
    }

    setCpLoading(true)
    try {
      await apiClient.post('/auth/change-password', {
        username: cpUsername,
        current_password: cpCurrentPassword,
        new_password: cpNewPassword,
      })
      setCpSuccess(true)
      setCpError(null)
      // Clear form after success
      setTimeout(() => {
        setCpCurrentPassword('')
        setCpNewPassword('')
        setCpConfirmPassword('')
      }, 1000)
    } catch {
      setCpError(t.auth.passwordChangeFailed)
    } finally {
      setCpLoading(false)
    }
  }

  const openChangePassword = () => {
    setCpUsername(username) // Pre-fill with login username if available
    setCpCurrentPassword('')
    setCpNewPassword('')
    setCpConfirmPassword('')
    setCpError(null)
    setCpSuccess(false)
    setChangePasswordOpen(true)
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle>{t.auth.loginTitle}</CardTitle>
          <CardDescription>
            {t.auth.loginDesc}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Input
                type="text"
                placeholder={t.auth.usernamePlaceholder || 'Username'}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={isLoading}
                autoComplete="username"
              />
            </div>
            <div>
              <Input
                type="password"
                placeholder={t.auth.passwordPlaceholder}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
                autoComplete="current-password"
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 text-red-600 text-sm">
                <AlertCircle className="h-4 w-4" />
                {error}
              </div>
            )}

            <Button
              type="submit"
              className="w-full"
              disabled={isLoading || !username.trim() || !password.trim()}
            >
              {isLoading ? t.auth.signingIn : t.auth.signIn}
            </Button>

            <Button
              type="button"
              variant="ghost"
              className="w-full text-xs text-muted-foreground"
              onClick={openChangePassword}
            >
              <KeyRound className="h-3.5 w-3.5 mr-1.5" />
              {t.auth.changePassword}
            </Button>

            {configInfo && (
              <div className="text-xs text-center text-muted-foreground pt-2 border-t">
                <div>{t.common.version} {configInfo.version}</div>
                <div className="font-mono text-[10px]">{configInfo.apiUrl}</div>
              </div>
            )}
          </form>
        </CardContent>
      </Card>

      {/* Change Password Dialog */}
      <Dialog open={changePasswordOpen} onOpenChange={setChangePasswordOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t.auth.changePasswordTitle}</DialogTitle>
            <DialogDescription>{t.auth.changePasswordDesc}</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleChangePassword} className="space-y-4">
            <div>
              <Input
                type="text"
                placeholder={t.auth.usernamePlaceholder || 'Username'}
                value={cpUsername}
                onChange={(e) => setCpUsername(e.target.value)}
                disabled={cpLoading}
                autoComplete="username"
              />
            </div>
            <div>
              <Input
                type="password"
                placeholder={t.auth.currentPassword}
                value={cpCurrentPassword}
                onChange={(e) => setCpCurrentPassword(e.target.value)}
                disabled={cpLoading}
                autoComplete="current-password"
              />
            </div>
            <div>
              <Input
                type="password"
                placeholder={t.auth.newPassword}
                value={cpNewPassword}
                onChange={(e) => setCpNewPassword(e.target.value)}
                disabled={cpLoading}
                autoComplete="new-password"
              />
            </div>
            <div>
              <Input
                type="password"
                placeholder={t.auth.confirmNewPassword}
                value={cpConfirmPassword}
                onChange={(e) => setCpConfirmPassword(e.target.value)}
                disabled={cpLoading}
                autoComplete="new-password"
              />
            </div>

            {cpError && (
              <div className="flex items-center gap-2 text-red-600 text-sm">
                <AlertCircle className="h-4 w-4 flex-shrink-0" />
                {cpError}
              </div>
            )}

            {cpSuccess && (
              <div className="flex items-center gap-2 text-green-600 text-sm">
                <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
                {t.auth.passwordChangeSuccess}
              </div>
            )}

            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                onClick={() => setChangePasswordOpen(false)}
              >
                {t.common.cancel}
              </Button>
              <Button
                type="submit"
                className="flex-1"
                disabled={cpLoading || !cpUsername.trim() || !cpCurrentPassword.trim() || !cpNewPassword.trim() || !cpConfirmPassword.trim()}
              >
                {cpLoading ? t.auth.changingPassword : t.common.confirm}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}