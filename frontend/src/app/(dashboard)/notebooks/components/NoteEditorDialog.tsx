'use client'

import { Controller, useForm, useWatch } from 'react-hook-form'
import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useCreateNote, useUpdateNote, useNote } from '@/lib/hooks/use-notes'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { MarkdownEditor } from '@/components/ui/markdown-editor'
import { InlineEdit } from '@/components/common/InlineEdit'
import { cn } from "@/lib/utils";
import { useTranslation } from '@/lib/hooks/use-translation'
import { exportToPdf, exportToHtml } from '@/lib/utils/export-note'
import { FileDown, FileText, Globe, Presentation } from 'lucide-react'
import { PptTaskList } from '@/components/common/PptTaskList'
import { useGeneratePpt } from '@/lib/hooks/use-ppt'
import { Textarea } from '@/components/ui/textarea'

const createNoteSchema = z.object({
  title: z.string().optional(),
  content: z.string().min(1, 'Content is required'),
})

type CreateNoteFormData = z.infer<typeof createNoteSchema>

interface NoteEditorDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  notebookId: string
  note?: { id: string; title: string | null; content: string | null }
}

export function NoteEditorDialog({ open, onOpenChange, notebookId, note }: NoteEditorDialogProps) {
  const { t } = useTranslation()
  const createNote = useCreateNote()
  const updateNote = useUpdateNote()
  const queryClient = useQueryClient()
  const isEditing = Boolean(note)

  // Ensure note ID has 'note:' prefix for API calls
  const noteIdWithPrefix = note?.id
    ? (note.id.includes(':') ? note.id : `note:${note.id}`)
    : ''

  const { data: fetchedNote, isLoading: noteLoading } = useNote(noteIdWithPrefix, { enabled: open && !!note?.id })
  const isSaving = isEditing ? updateNote.isPending : createNote.isPending
  const {
    handleSubmit,
    control,
    formState: { errors },
    reset,
    setValue,
  } = useForm<CreateNoteFormData>({
    resolver: zodResolver(createNoteSchema),
    defaultValues: {
      title: '',
      content: '',
    },
  })
  const watchTitle = useWatch({ control, name: 'title' })
  const watchContent = useWatch({ control, name: 'content' })
  const [isEditorFullscreen, setIsEditorFullscreen] = useState(false)
  const [pptDialogOpen, setPptDialogOpen] = useState(false)
  const [pptPrompt, setPptPrompt] = useState('')
  const generatePpt = useGeneratePpt()

  useEffect(() => {
    if (!open) {
      reset({ title: '', content: '' })
      return
    }

    const source = fetchedNote ?? note
    const title = source?.title ?? ''
    const content = source?.content ?? ''

    reset({ title, content })
  }, [open, note, fetchedNote, reset])

  useEffect(() => {
    if (!open) return

    const observer = new MutationObserver(() => {
      setIsEditorFullscreen(!!document.querySelector('.w-md-editor-fullscreen'))
    })
    observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [open])

  const onSubmit = async (data: CreateNoteFormData) => {
    if (note) {
      await updateNote.mutateAsync({
        id: noteIdWithPrefix,
        data: {
          title: data.title || undefined,
          content: data.content,
        },
      })
      // Only invalidate notebook-specific queries if we have a notebookId
      if (notebookId) {
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notes(notebookId) })
      }
    } else {
      // Creating a note requires a notebookId
      if (!notebookId) {
        console.error('Cannot create note without notebook_id')
        return
      }
      await createNote.mutateAsync({
        title: data.title || undefined,
        content: data.content,
        note_type: 'human',
        notebook_id: notebookId,
      })
    }
    reset()
    onOpenChange(false)
  }

  const handleClose = () => {
    reset()
    setIsEditorFullscreen(false)
    onOpenChange(false)
  }

  const handleGeneratePpt = async () => {
    if (!noteIdWithPrefix) return
    try {
      await generatePpt.mutateAsync({
        noteId: noteIdWithPrefix,
        userPrompt: pptPrompt.trim() || undefined,
      })
    } catch {
      // Error handled by mutation's onError if needed
    }
    setPptPrompt('')
    setPptDialogOpen(false)
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className={cn(
        "sm:max-w-3xl w-full max-h-[90vh] overflow-hidden p-0",
        isEditorFullscreen && "!max-w-screen !max-h-screen border-none w-screen h-screen"
      )}>
        <DialogTitle className="sr-only">
          {isEditing ? t.sources.editNote : t.sources.createNote}
        </DialogTitle>
        <form onSubmit={handleSubmit(onSubmit)} className="flex h-full flex-col min-w-0">
          {isEditing && noteLoading ? (
            <div className="flex-1 flex items-center justify-center py-10">
              <span className="text-sm text-muted-foreground">{t.common.loading}</span>
            </div>
          ) : (
            <>
              <div className="border-b px-6 py-4">
                <InlineEdit
                  id="note-title"
                  name="title"
                  value={watchTitle ?? ''}
                  onSave={(value) => setValue('title', value || '')}
                  placeholder={t.sources.addTitle}
                  emptyText={t.sources.untitledNote}
                  className="text-xl font-semibold"
                  inputClassName="text-xl font-semibold"
                />
              </div>

              <div className={cn(
                "flex-1 overflow-y-auto",
                !isEditorFullscreen && "px-6 py-4")
              }>
                <Controller
                  control={control}
                  name="content"
                  render={({ field }) => (
                    <MarkdownEditor
                      key={note?.id ?? 'new'}
                      textareaId="note-content"
                      value={field.value}
                      onChange={field.onChange}
                      height={420}
                      placeholder={t.sources.writeNotePlaceholder}
                      className={cn(
                        "w-full h-full min-h-[420px] max-h-[500px] overflow-hidden [&_.w-md-editor]:!static [&_.w-md-editor]:!w-full [&_.w-md-editor]:!h-full [&_.w-md-editor-content]:overflow-y-auto",
                        !isEditorFullscreen && "rounded-md border"
                      )}
                    />
                  )}
                />
                {errors.content && (
                  <p className="text-sm text-red-600 mt-1">{errors.content.message}</p>
                )}
              </div>
            </>
          )}

          <div className="border-t px-6 py-4">
            <div className="flex items-center gap-2">
              {isEditing && watchContent && (
                <div className="flex gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => exportToPdf(watchContent, watchTitle || undefined)}
                  >
                    <FileText className="h-3.5 w-3.5 mr-1" />
                    PDF
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => exportToHtml(watchContent, watchTitle || undefined)}
                  >
                    <Globe className="h-3.5 w-3.5 mr-1" />
                    HTML
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-xs text-muted-foreground hover:text-foreground"
                    onClick={async () => {
                      if (!noteIdWithPrefix) return
                      try {
                        const { default: apiClient } = await import('@/lib/api/client')
                        const response = await apiClient.get(
                          `/notes/${encodeURIComponent(noteIdWithPrefix)}/export/docx`,
                          { responseType: 'blob' }
                        )
                        const blob = new Blob([response.data], {
                          type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                        })
                        const url = URL.createObjectURL(blob)
                        const link = document.createElement('a')
                        link.href = url
                        link.download = `${watchTitle || 'note'}.docx`
                        document.body.appendChild(link)
                        link.click()
                        document.body.removeChild(link)
                        URL.revokeObjectURL(url)
                      } catch (err) {
                        console.error('Word export failed:', err)
                        alert('Word export failed')
                      }
                    }}
                  >
                    <FileDown className="h-3.5 w-3.5 mr-1" />
                    Word
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-xs bg-purple-100 hover:bg-purple-200 text-purple-700 dark:bg-purple-900/30 dark:hover:bg-purple-900/50 dark:text-purple-300"
                    onClick={() => setPptDialogOpen(true)}
                    disabled={generatePpt.isPending}
                  >
                    <Presentation className="h-3.5 w-3.5 mr-1" />
                    {t.notes?.generatePpt || 'Make PPT'}
                  </Button>
                </div>
              )}
              <div className="flex-1" />
              <Button type="button" variant="outline" onClick={handleClose}>
                {t.common.cancel}
              </Button>
              <Button
                type="submit"
                disabled={isSaving || (isEditing && noteLoading)}
              >
                {isSaving
                  ? isEditing ? `${t.common.saving}...` : `${t.common.creating}...`
                  : isEditing
                    ? t.sources.saveNote
                    : t.sources.createNoteBtn}
              </Button>
            </div>

            {/* PPT task list — always visible below toolbar when editing */}
            {isEditing && noteIdWithPrefix && (
              <PptTaskList noteId={noteIdWithPrefix} />
            )}
          </div>
        </form>
      </DialogContent>

      {/* PPT prompt — separate popup dialog */}
      <Dialog open={pptDialogOpen} onOpenChange={setPptDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogTitle>{t.notes?.pptRequirements || 'PPT Requirements (optional)'}</DialogTitle>
          <Textarea
            value={pptPrompt}
            onChange={(e) => setPptPrompt(e.target.value)}
            placeholder={t.notes?.pptPromptPlaceholder || 'e.g. Focus on key findings, keep it under 10 slides...'}
            className="min-h-[80px] text-sm"
          />
          <div className="flex gap-2 justify-end">
            <Button type="button" variant="ghost" onClick={() => setPptDialogOpen(false)}>
              {t.common.cancel}
            </Button>
            <Button
              type="button"
              className="bg-purple-600 hover:bg-purple-700 text-white"
              onClick={handleGeneratePpt}
              disabled={generatePpt.isPending}
            >
              {generatePpt.isPending ? `${t.notes?.generating || 'Generating'}...` : t.notes?.startGeneration || 'Start'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Dialog>
  )
}

