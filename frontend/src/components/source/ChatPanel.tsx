'use client'

import { useState, useRef, useEffect, useId, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Bot, User, Send, Loader2, FileText, Lightbulb, StickyNote, Clock, Microscope, StopCircle } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  SourceChatMessage,
  SourceChatContextIndicator,
  BaseChatSession
} from '@/lib/types/api'
import { ModelSelector } from './ModelSelector'
import { ContextIndicator } from '@/components/common/ContextIndicator'
import { SessionManager } from '@/components/source/SessionManager'
import { MessageActions } from '@/components/source/MessageActions'
import { convertReferencesToCompactMarkdown, createCompactReferenceLinkComponent } from '@/lib/utils/source-references'
import { useModalManager } from '@/lib/hooks/use-modal-manager'
import { toast } from 'sonner'
import { useTranslation } from '@/lib/hooks/use-translation'
import { startDeepResearch, getDeepResearchStatus, getActiveDeepResearch, cancelDeepResearch, DeepResearchEvent } from '@/lib/api/deep-research'
import { DeepResearchProgress } from './DeepResearchProgress'

interface NotebookContextStats {
  sourcesInsights: number
  sourcesFull: number
  notesCount: number
  tokenCount?: number
  charCount?: number
}

interface ChatPanelProps {
  messages: SourceChatMessage[]
  isStreaming: boolean
  contextIndicators: SourceChatContextIndicator | null
  onSendMessage: (message: string, modelOverride?: string) => void
  modelOverride?: string
  onModelChange?: (model?: string) => void
  // Session management props
  sessions?: BaseChatSession[]
  currentSessionId?: string | null
  onCreateSession?: (title: string) => void
  onSelectSession?: (sessionId: string) => void
  onDeleteSession?: (sessionId: string) => void
  onUpdateSession?: (sessionId: string, title: string) => void
  loadingSessions?: boolean
  // Generic props for reusability
  title?: string
  contextType?: 'source' | 'notebook'
  // Notebook context stats (for notebook chat)
  notebookContextStats?: NotebookContextStats
  // Notebook ID for saving notes
  notebookId?: string
}

export function ChatPanel({
  messages,
  isStreaming,
  contextIndicators,
  onSendMessage,
  modelOverride,
  onModelChange,
  sessions = [],
  currentSessionId,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
  onUpdateSession,
  loadingSessions = false,
  title,
  contextType = 'source',
  notebookContextStats,
  notebookId
}: ChatPanelProps) {
  const { t } = useTranslation()
  const chatInputId = useId()
  const [input, setInput] = useState('')
  const [sessionManagerOpen, setSessionManagerOpen] = useState(false)
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { openModal } = useModalManager()

  // Deep Research state
  const [deepResearchMode, setDeepResearchMode] = useState(false)
  const [deepResearchRunning, setDeepResearchRunning] = useState(false)
  const [deepResearchEvents, setDeepResearchEvents] = useState<DeepResearchEvent[]>([])
  const [deepResearchReport, setDeepResearchReport] = useState<string | null>(null)
  const [deepResearchError, setDeepResearchError] = useState<string | null>(null)
  const [deepResearchJobId, setDeepResearchJobId] = useState<string | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const eventsCursorRef = useRef(0)

  // Stop polling helper
  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

  // Poll for job status
  const pollJobStatus = useCallback(async (jobId: string) => {
    try {
      const status = await getDeepResearchStatus(jobId, eventsCursorRef.current)

      // Append new events
      if (status.events && status.events.length > 0) {
        setDeepResearchEvents(prev => [...prev, ...status.events])
        eventsCursorRef.current += status.events.length
      }

      // Check completion
      if (status.status === 'completed') {
        setDeepResearchRunning(false)
        if (status.final_report) {
          setDeepResearchReport(status.final_report)
        }
        stopPolling()
      } else if (status.status === 'failed') {
        setDeepResearchRunning(false)
        setDeepResearchError(status.error || 'Deep research failed')
        toast.error(status.error || 'Deep research failed')
        stopPolling()
      } else if (status.status === 'cancelled') {
        setDeepResearchRunning(false)
        stopPolling()
      }
    } catch (e) {
      console.warn('Failed to poll deep research status:', e)
    }
  }, [stopPolling])

  // Start polling for a job
  const startPolling = useCallback((jobId: string) => {
    stopPolling()
    pollingRef.current = setInterval(() => pollJobStatus(jobId), 2000)
    // Also poll immediately
    pollJobStatus(jobId)
  }, [stopPolling, pollJobStatus])

  // Check for active job on mount (resume after navigation)
  useEffect(() => {
    if (!notebookId) return
    let cancelled = false

    const checkActiveJob = async () => {
      try {
        console.log('[DeepResearch] Checking active job for notebook:', notebookId)
        const active = await getActiveDeepResearch(notebookId)
        console.log('[DeepResearch] Active job result:', active)
        if (cancelled || !active) return

        if (active.status === 'completed') {
          // Show completed result
          console.log('[DeepResearch] Showing completed job:', active.job_id)
          setDeepResearchMode(true)
          setDeepResearchEvents(active.events || [])
          if (active.final_report) {
            setDeepResearchReport(active.final_report)
          }
          setDeepResearchJobId(active.job_id)
        } else if (active.status !== 'failed') {
          // Any status other than 'completed' or 'failed' means still running
          // (status gets overwritten with step descriptions like "Outlined 5 sections")
          console.log('[DeepResearch] Resuming running job:', active.job_id, 'status:', active.status)
          setDeepResearchMode(true)
          setDeepResearchRunning(true)
          setDeepResearchJobId(active.job_id)
          setDeepResearchEvents(active.events || [])
          eventsCursorRef.current = (active.events || []).length
          startPolling(active.job_id)
        }
      } catch (e) {
        console.error('[DeepResearch] Error checking active job:', e)
      }
    }

    checkActiveJob()
    return () => { cancelled = true; stopPolling() }
  }, [notebookId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Cleanup polling on unmount
  useEffect(() => {
    return () => stopPolling()
  }, [stopPolling])

  const handleDeepResearch = useCallback(async (question: string) => {
    setDeepResearchRunning(true)
    setDeepResearchEvents([])
    setDeepResearchReport(null)
    setDeepResearchError(null)
    eventsCursorRef.current = 0

    try {
      const job = await startDeepResearch(question, notebookId, modelOverride)
      setDeepResearchJobId(job.job_id)
      startPolling(job.job_id)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Deep research failed'
      setDeepResearchError(msg)
      setDeepResearchRunning(false)
      toast.error(msg)
    }
  }, [modelOverride, notebookId, startPolling])

  const handleStopDeepResearch = useCallback(async () => {
    const jobId = deepResearchJobId
    stopPolling()
    setDeepResearchRunning(false)
    setDeepResearchMode(false)

    if (jobId) {
      try {
        await cancelDeepResearch(jobId)
        toast.success('Deep Research 已停止')
      } catch (e) {
        console.warn('Failed to cancel deep research:', e)
      }
    }
  }, [deepResearchJobId, stopPolling])

  const handleReferenceClick = (type: string, id: string) => {
    const modalType = type === 'source_insight' ? 'insight' : type as 'source' | 'note' | 'insight'

    try {
      openModal(modalType, id)
      // Note: The modal system uses URL parameters and doesn't throw errors for missing items.
      // The modal component itself will handle displaying "not found" states.
      // This try-catch is here for future enhancements or unexpected errors.
    } catch {
      toast.error(t.common.noResults)
    }
  }

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = () => {
    if (input.trim() && !isStreaming && !deepResearchRunning) {
      if (deepResearchMode) {
        handleDeepResearch(input.trim())
      } else {
        onSendMessage(input.trim(), modelOverride)
      }
      setInput('')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Detect platform for correct modifier key
    const isMac = typeof navigator !== 'undefined' && navigator.userAgent.toUpperCase().indexOf('MAC') >= 0
    const isModifierPressed = isMac ? e.metaKey : e.ctrlKey

    if (e.key === 'Enter' && isModifierPressed) {
      e.preventDefault()
      handleSend()
    }
  }

  // Detect platform for placeholder text
  const isMac = typeof navigator !== 'undefined' && navigator.userAgent.toUpperCase().indexOf('MAC') >= 0
  const keyHint = isMac ? '⌘+Enter' : 'Ctrl+Enter'

  return (
    <>
      <Card className="flex flex-col h-full flex-1 overflow-hidden">
        <CardHeader className="pb-3 flex-shrink-0">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Bot className="h-5 w-5" />
              {title || (contextType === 'source' ? t.chat.chatWith.replace('{name}', t.navigation.sources) : t.chat.chatWith.replace('{name}', t.common.notebook))}
            </CardTitle>
            {onSelectSession && onCreateSession && onDeleteSession && (
              <Dialog open={sessionManagerOpen} onOpenChange={setSessionManagerOpen}>
                <Button
                  variant="ghost"
                  size="sm"
                  className="gap-2"
                  onClick={() => setSessionManagerOpen(true)}
                  disabled={loadingSessions}
                >
                  <Clock className="h-4 w-4" />
                  <span className="text-xs">{t.chat.sessions}</span>
                </Button>
                <DialogContent className="sm:max-w-[420px] p-0 overflow-hidden">
                  <DialogTitle className="sr-only">{t.chat.sessionsTitle}</DialogTitle>
                  <SessionManager
                    sessions={sessions}
                    currentSessionId={currentSessionId ?? null}
                    onCreateSession={(title) => onCreateSession?.(title)}
                    onSelectSession={(sessionId) => {
                      onSelectSession(sessionId)
                      setSessionManagerOpen(false)
                    }}
                    onUpdateSession={(sessionId, title) => onUpdateSession?.(sessionId, title)}
                    onDeleteSession={(sessionId) => onDeleteSession?.(sessionId)}
                    loadingSessions={loadingSessions}
                  />
                </DialogContent>
              </Dialog>
            )}
          </div>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col min-h-0 p-0">
          <ScrollArea className="flex-1 min-h-0 px-4" ref={scrollAreaRef}>
            <div className="space-y-4 py-4">
              {messages.length === 0 ? (
                <div className="text-center text-muted-foreground py-8">
                  <Bot className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p className="text-sm">
                    {t.chat.startConversation.replace('{type}', contextType === 'source' ? t.navigation.sources : t.common.notebook)}
                  </p>
                  <p className="text-xs mt-2">{t.chat.askQuestions}</p>
                </div>
              ) : (
                messages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex gap-3 ${message.type === 'human' ? 'justify-end' : 'justify-start'
                      }`}
                  >
                    {message.type === 'ai' && (
                      <div className="flex-shrink-0">
                        <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                          <Bot className="h-4 w-4" />
                        </div>
                      </div>
                    )}
                    <div className="flex flex-col gap-2 max-w-[80%]">
                      <div
                        className={`rounded-lg px-4 py-2 ${message.type === 'human'
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted'
                          }`}
                      >
                        {message.type === 'ai' ? (
                          <AIMessageContent
                            content={message.content}
                            onReferenceClick={handleReferenceClick}
                          />
                        ) : (
                          <p className="text-sm break-all">{message.content}</p>
                        )}
                      </div>
                      {message.type === 'ai' && (
                        <MessageActions
                          content={message.content}
                          notebookId={notebookId}
                        />
                      )}
                    </div>
                    {message.type === 'human' && (
                      <div className="flex-shrink-0">
                        <div className="h-8 w-8 rounded-full bg-primary flex items-center justify-center">
                          <User className="h-4 w-4 text-primary-foreground" />
                        </div>
                      </div>
                    )}
                  </div>
                ))
              )}
              {isStreaming && (
                <div className="flex gap-3 justify-start">
                  <div className="flex-shrink-0">
                    <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                      <Bot className="h-4 w-4" />
                    </div>
                  </div>
                  <div className="rounded-lg px-4 py-2 bg-muted">
                    <Loader2 className="h-4 w-4 animate-spin" />
                  </div>
                </div>
              )}
              {/* Deep Research Progress */}
              {(deepResearchRunning || deepResearchReport || deepResearchError) && (
                <div className="flex gap-3 justify-start">
                  <div className="flex-shrink-0">
                    <div className="h-8 w-8 rounded-full bg-purple-500/10 flex items-center justify-center">
                      <Microscope className="h-4 w-4 text-purple-600" />
                    </div>
                  </div>
                  <div className="rounded-lg px-4 py-3 bg-muted max-w-[90%]">
                    <DeepResearchProgress
                      events={deepResearchEvents}
                      isRunning={deepResearchRunning}
                      report={deepResearchReport}
                      error={deepResearchError}
                    />
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>

          {/* Context Indicators */}
          {contextIndicators && (
            <div className="border-t px-4 py-2">
              <div className="flex flex-wrap gap-2 text-xs">
                {contextIndicators.sources?.length > 0 && (
                  <Badge variant="outline" className="gap-1">
                    <FileText className="h-3 w-3" />
                    {contextIndicators.sources.length} {t.navigation.sources}
                  </Badge>
                )}
                {contextIndicators.insights?.length > 0 && (
                  <Badge variant="outline" className="gap-1">
                    <Lightbulb className="h-3 w-3" />
                    {contextIndicators.insights.length} {contextIndicators.insights.length === 1 ? t.common.insight : t.common.insights}
                  </Badge>
                )}
                {contextIndicators.notes?.length > 0 && (
                  <Badge variant="outline" className="gap-1">
                    <StickyNote className="h-3 w-3" />
                    {contextIndicators.notes.length} {contextIndicators.notes.length === 1 ? t.common.note : t.common.notes}
                  </Badge>
                )}
              </div>
            </div>
          )}

          {/* Notebook Context Indicator */}
          {notebookContextStats && (
            <ContextIndicator
              sourcesInsights={notebookContextStats.sourcesInsights}
              sourcesFull={notebookContextStats.sourcesFull}
              notesCount={notebookContextStats.notesCount}
              tokenCount={notebookContextStats.tokenCount}
              charCount={notebookContextStats.charCount}
            />
          )}

          {/* Input Area */}
          <div className="flex-shrink-0 p-4 space-y-3 border-t">
            {/* Model selector + Deep Research toggle */}
            {onModelChange && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{t.chat.model}</span>
                <div className="flex items-center gap-2">
                  {contextType === 'notebook' && (
                    <Button
                      variant={deepResearchRunning ? 'destructive' : deepResearchMode ? 'default' : 'outline'}
                      size="sm"
                      className={`h-7 text-xs gap-1.5 ${deepResearchRunning
                        ? 'bg-red-600 hover:bg-red-700 text-white'
                        : deepResearchMode
                          ? 'bg-purple-600 hover:bg-purple-700 text-white'
                          : 'hover:border-purple-400 hover:text-purple-600'
                        }`}
                      onClick={deepResearchRunning ? handleStopDeepResearch : () => setDeepResearchMode(!deepResearchMode)}
                      disabled={isStreaming}
                    >
                      {deepResearchRunning ? (
                        <>
                          <StopCircle className="h-3 w-3" />
                          停止研究
                        </>
                      ) : (
                        <>
                          <Microscope className="h-3 w-3" />
                          Deep Research
                        </>
                      )}
                    </Button>
                  )}
                  <ModelSelector
                    currentModel={modelOverride}
                    onModelChange={onModelChange}
                    disabled={isStreaming}
                  />
                </div>
              </div>
            )}

            <div className="flex gap-2 items-end min-w-0">
              <Textarea
                id={chatInputId}
                name="chat-message"
                autoComplete="off"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={`${t.chat.sendPlaceholder} (${t.chat.pressToSend.replace('{key}', keyHint)})`}
                disabled={isStreaming}
                className="flex-1 min-h-[40px] max-h-[100px] resize-none py-2 px-3 min-w-0"
                rows={1}
              />
              <Button
                onClick={handleSend}
                disabled={!input.trim() || isStreaming || deepResearchRunning}
                size="icon"
                className={`h-[40px] w-[40px] flex-shrink-0 ${deepResearchMode && !isStreaming && !deepResearchRunning
                  ? 'bg-purple-600 hover:bg-purple-700'
                  : ''
                  }`}
              >
                {isStreaming || deepResearchRunning ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : deepResearchMode ? (
                  <Microscope className="h-4 w-4" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

    </>
  )
}

// Helper component to render AI messages with clickable references
function AIMessageContent({
  content,
  onReferenceClick
}: {
  content: string
  onReferenceClick: (type: string, id: string) => void
}) {
  const { t } = useTranslation()
  // Convert references to compact markdown with numbered citations
  const markdownWithCompactRefs = convertReferencesToCompactMarkdown(content, t.common.references)

  // Create custom link component for compact references
  const LinkComponent = createCompactReferenceLinkComponent(onReferenceClick)

  return (
    <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none break-words prose-headings:font-semibold prose-a:text-blue-600 prose-a:break-all prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-p:mb-4 prose-p:leading-7 prose-li:mb-2">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: LinkComponent,
          p: ({ children }) => <p className="mb-4">{children}</p>,
          h1: ({ children }) => <h1 className="mb-4 mt-6">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-3 mt-5">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-3 mt-4">{children}</h3>,
          h4: ({ children }) => <h4 className="mb-2 mt-4">{children}</h4>,
          h5: ({ children }) => <h5 className="mb-2 mt-3">{children}</h5>,
          h6: ({ children }) => <h6 className="mb-2 mt-3">{children}</h6>,
          li: ({ children }) => <li className="mb-1">{children}</li>,
          ul: ({ children }) => <ul className="mb-4 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="mb-4 space-y-1">{children}</ol>,
          table: ({ children }) => (
            <div className="my-4 overflow-x-auto">
              <table className="min-w-full border-collapse border border-border">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-b border-border">{children}</tr>,
          th: ({ children }) => <th className="border border-border px-3 py-2 text-left font-semibold">{children}</th>,
          td: ({ children }) => <td className="border border-border px-3 py-2">{children}</td>,
        }}
      >
        {markdownWithCompactRefs}
      </ReactMarkdown>
    </div>
  )
}
