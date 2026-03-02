'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { useTranslation } from '@/lib/hooks/use-translation'

interface CreateUserDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    onCreated: () => void
}

export function CreateUserDialog({ open, onOpenChange, onCreated }: CreateUserDialogProps) {
    const { t } = useTranslation()
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [isAdmin, setIsAdmin] = useState(false)
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const resetForm = () => {
        setUsername('')
        setPassword('')
        setIsAdmin(false)
        setError(null)
    }

    const handleOpenChange = (open: boolean) => {
        if (!open) {
            resetForm()
        }
        onOpenChange(open)
    }

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError(null)

        // Validate
        if (username.length < 2) {
            setError(t.admin.usernameTooShort)
            return
        }
        if (password.length < 4) {
            setError(t.admin.passwordTooShort)
            return
        }

        setIsLoading(true)
        try {
            const { adminApi } = await import('@/lib/api/admin')
            await adminApi.createUser({ username, password, is_admin: isAdmin })
            resetForm()
            onOpenChange(false)
            onCreated()
        } catch (err: unknown) {
            if (err && typeof err === 'object' && 'response' in err) {
                const axiosErr = err as { response?: { status?: number } }
                if (axiosErr.response?.status === 409) {
                    setError(t.admin.userAlreadyExists.replace('{name}', username))
                } else {
                    setError(t.admin.failedToCreate)
                }
            } else {
                setError(t.admin.failedToCreate)
            }
        } finally {
            setIsLoading(false)
        }
    }

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{t.admin.createUser}</DialogTitle>
                    <DialogDescription>{t.admin.desc}</DialogDescription>
                </DialogHeader>

                <form onSubmit={handleSubmit} className="space-y-4">
                    <div className="space-y-2">
                        <Label htmlFor="create-username">{t.admin.username}</Label>
                        <Input
                            id="create-username"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            placeholder={t.admin.username}
                            autoComplete="off"
                            autoFocus
                        />
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="create-password">{t.admin.password}</Label>
                        <Input
                            id="create-password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder={t.admin.password}
                            autoComplete="new-password"
                        />
                    </div>

                    <div className="flex items-center gap-3">
                        <input
                            id="create-is-admin"
                            type="checkbox"
                            checked={isAdmin}
                            onChange={(e) => setIsAdmin(e.target.checked)}
                            className="h-4 w-4 rounded border-gray-300"
                        />
                        <Label htmlFor="create-is-admin" className="cursor-pointer">
                            {t.admin.isAdmin}
                        </Label>
                    </div>

                    {error && (
                        <div className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded-md">
                            {error}
                        </div>
                    )}

                    <DialogFooter>
                        <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
                            {t.common.cancel}
                        </Button>
                        <Button type="submit" disabled={isLoading}>
                            {isLoading ? t.admin.creating : t.admin.createUser}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    )
}
