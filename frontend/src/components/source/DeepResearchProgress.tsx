'use client'

import { DeepResearchEvent } from '@/lib/api/deep-research'
import { Badge } from '@/components/ui/badge'
import { Loader2, Search, CheckCircle2, Brain, PenTool, FileText, AlertCircle } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { convertReferencesToCompactMarkdown, createCompactReferenceLinkComponent } from '@/lib/utils/source-references'
import { MessageActions } from '@/components/source/MessageActions'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useModalManager } from '@/lib/hooks/use-modal-manager'
import { toast } from 'sonner'

interface DeepResearchProgressProps {
    events: DeepResearchEvent[]
    isRunning: boolean
    report: string | null
    error: string | null
    notebookId?: string
    researchType?: string
}

interface SectionProgress {
    title: string
    description: string
    searchAttempts: number
    totalResults: number
    relevantCount?: number
    sufficient?: boolean
    written: boolean
    summarized: boolean
}

export function DeepResearchProgress({ events, isRunning, report, error, notebookId, researchType = 'deep' }: DeepResearchProgressProps) {
    const { t } = useTranslation()
    const { openModal } = useModalManager()

    const handleReferenceClick = (type: string, id: string) => {
        const modalType = type === 'source_insight' ? 'insight'
            : type === 'source_embedding' ? 'source'
                : type as 'source' | 'note' | 'insight'
        try {
            openModal(modalType, id)
        } catch {
            toast.error(t.common.noResults)
        }
    }

    // Build section progress from events
    const sections: SectionProgress[] = []
    let outlineReasoning = ''
    let isCompiling = false

    for (const event of events) {
        switch (event.type) {
            case 'outline':
                if (event.sections) {
                    for (const s of event.sections) {
                        sections.push({
                            title: s.title,
                            description: s.description,
                            searchAttempts: 0,
                            totalResults: 0,
                            written: false,
                            summarized: false,
                        })
                    }
                }
                if (event.reasoning) outlineReasoning = event.reasoning
                break
            case 'search_done':
                if (event.section_index !== undefined && sections[event.section_index]) {
                    sections[event.section_index].searchAttempts = event.attempt || 0
                    sections[event.section_index].totalResults = event.total_results || 0
                }
                break
            case 'evaluate':
                if (event.section_index !== undefined && sections[event.section_index]) {
                    sections[event.section_index].sufficient = event.sufficient
                    sections[event.section_index].relevantCount = event.relevant_count
                }
                break
            case 'write_done':
                if (event.section_index !== undefined && sections[event.section_index]) {
                    sections[event.section_index].written = true
                }
                break
            case 'summarize_done':
                if (event.section_index !== undefined && sections[event.section_index]) {
                    sections[event.section_index].summarized = true
                }
                break
            case 'compiling':
                isCompiling = true
                break
        }
    }

    // Determine label
    const researchLabel = researchType === 'quick' ? 'Quick Research' : 'Deep Research'

    // Show report if complete
    if (report) {
        const markdownWithCompactRefs = convertReferencesToCompactMarkdown(report, t.common.references)
        const LinkComponent = createCompactReferenceLinkComponent(handleReferenceClick)

        return (
            <div className="space-y-4">
                <div className="flex items-center gap-2 text-sm font-medium text-green-600 dark:text-green-400">
                    <CheckCircle2 className="h-4 w-4" />
                    {researchLabel} 完成
                </div>
                <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none break-words prose-headings:font-semibold prose-a:text-blue-600 prose-a:break-all">
                    <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                            a: LinkComponent,
                        }}
                    >
                        {markdownWithCompactRefs}
                    </ReactMarkdown>
                </div>
                <MessageActions
                    content={report}
                    notebookId={notebookId}
                />
            </div>
        )
    }

    // Show error if any
    if (error) {
        return (
            <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium text-destructive">
                    <AlertCircle className="h-4 w-4" />
                    研究失败
                </div>
                <p className="text-sm text-muted-foreground">{error}</p>
            </div>
        )
    }

    // Show progress
    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium">
                <Brain className="h-4 w-4 text-primary" />
                {researchLabel}
                {isRunning && <Loader2 className="h-3 w-3 animate-spin ml-1" />}
            </div>

            {/* Outline */}
            {sections.length > 0 && (
                <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400">
                        <CheckCircle2 className="h-3 w-3" />
                        大纲已制定 ({sections.length} 个章节)
                    </div>
                    {outlineReasoning && (
                        <p className="text-xs text-muted-foreground ml-5">{outlineReasoning}</p>
                    )}
                </div>
            )}

            {/* Section progress */}
            {sections.map((section, i) => (
                <div key={i} className="ml-2 border-l-2 border-muted pl-3 py-1 space-y-1">
                    <div className="flex items-center gap-2">
                        {section.summarized ? (
                            <CheckCircle2 className="h-3.5 w-3.5 text-green-500 flex-shrink-0" />
                        ) : section.written ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary flex-shrink-0" />
                        ) : section.searchAttempts > 0 ? (
                            <Search className="h-3.5 w-3.5 text-blue-500 flex-shrink-0" />
                        ) : (
                            <div className="h-3.5 w-3.5 rounded-full border border-muted-foreground/30 flex-shrink-0" />
                        )}
                        <span className="text-xs font-medium">{section.title}</span>
                    </div>

                    {/* Search info */}
                    {section.searchAttempts > 0 && (
                        <div className="ml-5 flex flex-wrap gap-1.5">
                            <Badge variant="outline" className="text-[10px] h-4 px-1.5">
                                <Search className="h-2.5 w-2.5 mr-0.5" />
                                搜索 ×{section.searchAttempts}
                            </Badge>
                            <Badge variant="outline" className="text-[10px] h-4 px-1.5">
                                {section.totalResults} 条结果
                            </Badge>
                            {section.relevantCount !== undefined && (
                                <Badge variant="outline" className="text-[10px] h-4 px-1.5">
                                    {section.relevantCount} 条相关
                                </Badge>
                            )}
                            {section.written && (
                                <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                                    <PenTool className="h-2.5 w-2.5 mr-0.5" />
                                    已撰写
                                </Badge>
                            )}
                            {section.summarized && (
                                <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                                    <FileText className="h-2.5 w-2.5 mr-0.5" />
                                    已摘要
                                </Badge>
                            )}
                        </div>
                    )}
                </div>
            ))}

            {/* Compiling indicator */}
            {!report && (isCompiling || (sections.length > 0 && sections.every(s => s.summarized) && isRunning)) && (
                <div className="flex items-center gap-1.5 text-xs text-primary">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    📋 正在汇编最终报告...
                </div>
            )}
        </div>
    )
}
