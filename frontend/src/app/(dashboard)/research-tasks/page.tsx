'use client'

import { useTranslation } from '@/lib/hooks/use-translation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AppShell } from '@/components/layout/AppShell'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ListTodo, StopCircle, RefreshCw } from 'lucide-react'
import apiClient from '@/lib/api/client'
import { cancelDeepResearch } from '@/lib/api/deep-research'

interface RunningJob {
    job_id: string
    question: string
    status: string
    notebook_name: string | null
    notebook_id: string | null
    created: string | null
}

export default function ResearchTasksPage() {
    const { t } = useTranslation()
    const queryClient = useQueryClient()

    const { data: runningJobs = [], isLoading, refetch } = useQuery<RunningJob[]>({
        queryKey: ['deep-research-jobs'],
        queryFn: async () => {
            const res = await apiClient.get<RunningJob[]>('/deep-research/jobs')
            return res.data
        },
        refetchInterval: 5000,
    })

    const cancelJobMutation = useMutation({
        mutationFn: (jobId: string) => cancelDeepResearch(jobId),
        onSuccess: () => {
            toast.success(t.searchPage.taskCancelled)
            queryClient.invalidateQueries({ queryKey: ['deep-research-jobs'] })
        },
        onError: () => {
            toast.error('Failed to cancel task')
        },
    })

    return (
        <AppShell>
            <div className="p-4 md:p-6">
                <div className="flex items-center justify-between mb-4 md:mb-6">
                    <h1 className="text-xl md:text-2xl font-bold">{t.navigation.researchTasks}</h1>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => refetch()}
                        disabled={isLoading}
                    >
                        <RefreshCw className={`h-4 w-4 mr-1.5 ${isLoading ? 'animate-spin' : ''}`} />
                        {t.common.refresh || 'Refresh'}
                    </Button>
                </div>

                <Card>
                    <CardHeader>
                        <CardTitle className="text-lg">{t.searchPage.runningTasks}</CardTitle>
                        <p className="text-sm text-muted-foreground">
                            {t.searchPage.runningTasksDesc}
                        </p>
                    </CardHeader>
                    <CardContent>
                        {isLoading ? (
                            <div className="flex items-center justify-center py-8">
                                <LoadingSpinner size="lg" />
                            </div>
                        ) : runningJobs.length === 0 ? (
                            <div className="text-center py-8 text-muted-foreground">
                                <ListTodo className="h-12 w-12 mx-auto mb-4 opacity-30" />
                                <p>{t.searchPage.noRunningTasks}</p>
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {runningJobs.map((job) => (
                                    <Card key={job.job_id} className="border">
                                        <CardContent className="pt-4 pb-3">
                                            <div className="flex items-start justify-between gap-3">
                                                <div className="flex-1 min-w-0">
                                                    <p className="font-medium text-sm truncate" title={job.question}>
                                                        {job.question}
                                                    </p>
                                                    <div className="flex flex-wrap items-center gap-2 mt-1.5">
                                                        <Badge variant="secondary" className="text-xs">
                                                            {job.notebook_name || t.searchPage.unknownNotebook}
                                                        </Badge>
                                                        <Badge variant="outline" className="text-xs">
                                                            {job.status}
                                                        </Badge>
                                                        {job.created && (
                                                            <span className="text-xs text-muted-foreground">
                                                                {new Date(job.created).toLocaleString()}
                                                            </span>
                                                        )}
                                                    </div>
                                                </div>
                                                <Button
                                                    variant="destructive"
                                                    size="sm"
                                                    onClick={() => {
                                                        if (confirm(t.searchPage.cancelTaskConfirm)) {
                                                            cancelJobMutation.mutate(job.job_id)
                                                        }
                                                    }}
                                                    disabled={cancelJobMutation.isPending}
                                                    className="flex-shrink-0"
                                                >
                                                    <StopCircle className="h-3.5 w-3.5 mr-1" />
                                                    {t.searchPage.cancelTask}
                                                </Button>
                                            </div>
                                        </CardContent>
                                    </Card>
                                ))}
                            </div>
                        )}
                    </CardContent>
                </Card>
            </div>
        </AppShell>
    )
}
