'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useToast } from '@/lib/hooks/use-toast'
import { adminApi, User } from '@/lib/api/admin'
import { CreateUserDialog } from './components/CreateUserDialog'
import {
    UserPlus,
    Trash2,
    Shield,
    User as UserIcon,
    RefreshCw,
    Loader2,
    FileText,
    StickyNote,
} from 'lucide-react'

export default function UsersPage() {
    const { t } = useTranslation()
    const { isAdmin } = useAuthStore()
    const { toast } = useToast()
    const router = useRouter()

    const [users, setUsers] = useState<User[]>([])
    const [isLoading, setIsLoading] = useState(true)
    const [isCreateOpen, setIsCreateOpen] = useState(false)
    const [deletingUser, setDeletingUser] = useState<string | null>(null)

    // Use refs to avoid infinite useEffect loops (toast/t change every render)
    const toastRef = useRef(toast)
    const tRef = useRef(t)
    useEffect(() => { toastRef.current = toast }, [toast])
    useEffect(() => { tRef.current = t }, [t])

    // Redirect non-admin users
    useEffect(() => {
        if (!isAdmin) {
            router.push('/notebooks')
        }
    }, [isAdmin, router])

    const loadUsers = useCallback(async () => {
        setIsLoading(true)
        try {
            const data = await adminApi.listUsers()
            setUsers(data)
        } catch {
            toastRef.current({
                title: tRef.current.admin.failedToLoad,
                variant: 'destructive',
            })
        } finally {
            setIsLoading(false)
        }
    }, [])

    useEffect(() => {
        if (isAdmin) {
            loadUsers()
        }
    }, [isAdmin, loadUsers])

    const handleDelete = async (username: string) => {
        if (username === 'admin') {
            toast({
                title: t.admin.cannotDeleteAdmin,
                variant: 'destructive',
            })
            return
        }

        if (!window.confirm(t.admin.deleteConfirm.replace('{name}', username))) {
            return
        }

        setDeletingUser(username)
        try {
            await adminApi.deleteUser(username)
            toast({
                title: t.admin.userDeleted.replace('{name}', username),
            })
            loadUsers()
        } catch {
            toast({
                title: t.admin.failedToDelete,
                variant: 'destructive',
            })
        } finally {
            setDeletingUser(null)
        }
    }

    const handleUserCreated = () => {
        toast({
            title: t.common.success,
        })
        loadUsers()
    }

    if (!isAdmin) {
        return null
    }

    return (
        <AppShell>
            <div className="flex-1 overflow-y-auto">
                <div className="p-6">
                    <div className="max-w-4xl">
                        {/* Header */}
                        <div className="flex items-center justify-between mb-6">
                            <div>
                                <h1 className="text-2xl font-bold">{t.admin.title}</h1>
                                <p className="text-sm text-muted-foreground mt-1">{t.admin.desc}</p>
                            </div>
                            <div className="flex items-center gap-2">
                                <Button variant="outline" size="sm" onClick={loadUsers} disabled={isLoading}>
                                    <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
                                </Button>
                                <Button onClick={() => setIsCreateOpen(true)} size="sm">
                                    <UserPlus className="h-4 w-4 mr-2" />
                                    {t.admin.createUser}
                                </Button>
                            </div>
                        </div>

                        {/* User List */}
                        {isLoading ? (
                            <div className="flex items-center justify-center py-12">
                                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                            </div>
                        ) : users.length === 0 ? (
                            <div className="text-center py-12 text-muted-foreground">
                                {t.admin.noUsers}
                            </div>
                        ) : (
                            <div className="border rounded-lg divide-y">
                                {users.map((user) => (
                                    <div
                                        key={user.username}
                                        className="flex items-center justify-between px-4 py-3 hover:bg-muted/50 transition-colors"
                                    >
                                        <div className="flex items-center gap-3">
                                            <div className="flex items-center justify-center h-9 w-9 rounded-full bg-primary/10">
                                                {user.is_admin ? (
                                                    <Shield className="h-4 w-4 text-primary" />
                                                ) : (
                                                    <UserIcon className="h-4 w-4 text-muted-foreground" />
                                                )}
                                            </div>
                                            <div>
                                                <div className="font-medium flex items-center gap-2">
                                                    {user.username}
                                                    {user.is_admin && (
                                                        <Badge variant="default" className="text-xs">
                                                            {t.admin.adminRole}
                                                        </Badge>
                                                    )}
                                                </div>
                                                {user.created && (
                                                    <div className="text-xs text-muted-foreground">
                                                        {t.admin.createdAt}: {new Date(user.created).toLocaleDateString()}
                                                    </div>
                                                )}
                                            </div>
                                        </div>

                                        <div className="flex items-center gap-2">
                                            <Badge variant={user.is_admin ? 'default' : 'secondary'}>
                                                {user.is_admin ? t.admin.adminRole : t.admin.userRole}
                                            </Badge>
                                            <Badge variant="outline" className="gap-1 text-xs">
                                                <FileText className="h-3 w-3" />
                                                {user.source_count ?? 0}
                                            </Badge>
                                            <Badge variant="outline" className="gap-1 text-xs">
                                                <StickyNote className="h-3 w-3" />
                                                {user.note_count ?? 0}
                                            </Badge>
                                            {user.username !== 'admin' && (
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={() => handleDelete(user.username)}
                                                    disabled={deletingUser === user.username}
                                                    className="text-destructive hover:text-destructive hover:bg-destructive/10"
                                                >
                                                    {deletingUser === user.username ? (
                                                        <Loader2 className="h-4 w-4 animate-spin" />
                                                    ) : (
                                                        <Trash2 className="h-4 w-4" />
                                                    )}
                                                </Button>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            <CreateUserDialog
                open={isCreateOpen}
                onOpenChange={setIsCreateOpen}
                onCreated={handleUserCreated}
            />
        </AppShell>
    )
}
