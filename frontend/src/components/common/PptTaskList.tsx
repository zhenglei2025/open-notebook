'use client'

import { useState } from 'react'
import { Loader2, CheckCircle, AlertTriangle, Download, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { usePptTasks, useDeletePpt, downloadPptMarkdown } from '@/lib/hooks/use-ppt'
import { useTranslation } from '@/lib/hooks/use-translation'
import { NotePptTask } from '@/lib/types/api'

interface PptTaskListProps {
    noteId: string
}

const STATUS_CONFIG = {
    queued: { icon: Loader2, color: 'text-blue-600', spin: true },
    running: { icon: Loader2, color: 'text-purple-600', spin: true },
    completed: { icon: CheckCircle, color: 'text-green-600', spin: false },
    failed: { icon: AlertTriangle, color: 'text-red-600', spin: false },
} as const

export function PptTaskList({ noteId }: PptTaskListProps) {
    const { t } = useTranslation()
    const { data: tasks } = usePptTasks(noteId)
    const deletePpt = useDeletePpt()
    const [downloading, setDownloading] = useState<string | null>(null)

    if (!tasks || tasks.length === 0) return null

    const handleDownload = async (task: NotePptTask) => {
        setDownloading(task.id)
        try {
            await downloadPptMarkdown(task.id)
        } finally {
            setDownloading(null)
        }
    }

    const handleDelete = (task: NotePptTask) => {
        deletePpt.mutate(task.id)
    }

    return (
        <div className="border-t pt-3 mt-1">
            <div className="text-xs font-medium text-muted-foreground mb-2">
                {t.notes?.pptTasks || 'PPT Tasks'}
            </div>
            <div className="space-y-1.5 max-h-[120px] overflow-y-auto">
                {tasks.map((task) => {
                    const config = STATUS_CONFIG[task.status] || STATUS_CONFIG.queued
                    const StatusIcon = config.icon
                    const isProcessing = task.status === 'queued' || task.status === 'running'

                    return (
                        <div
                            key={task.id}
                            className="flex items-center justify-between gap-2 px-2 py-1.5 rounded-md bg-muted/50 text-sm"
                        >
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                                <StatusIcon
                                    className={cn('h-3.5 w-3.5 flex-shrink-0', config.color, config.spin && 'animate-spin')}
                                />
                                <span className="truncate text-xs">{task.title}</span>
                            </div>

                            <div className="flex items-center gap-1 flex-shrink-0">
                                {task.status === 'completed' && (
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="sm"
                                        className="h-6 w-6 p-0"
                                        onClick={() => handleDownload(task)}
                                        disabled={downloading === task.id}
                                        title={t.notes?.downloadMarkdown || 'Download'}
                                    >
                                        {downloading === task.id ? (
                                            <Loader2 className="h-3 w-3 animate-spin" />
                                        ) : (
                                            <Download className="h-3 w-3" />
                                        )}
                                    </Button>
                                )}

                                {task.status === 'failed' && task.error_message && (
                                    <span className="text-xs text-red-500 truncate max-w-[120px]" title={task.error_message}>
                                        {t.common?.error || 'Error'}
                                    </span>
                                )}

                                {!isProcessing && (
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="sm"
                                        className="h-6 w-6 p-0 text-muted-foreground hover:text-red-500"
                                        onClick={() => handleDelete(task)}
                                        disabled={deletePpt.isPending}
                                    >
                                        <Trash2 className="h-3 w-3" />
                                    </Button>
                                )}
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
