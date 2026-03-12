'use client'

import dynamic from 'next/dynamic'
import { forwardRef } from 'react'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'

const MDEditor = dynamic(
  () => import('@uiw/react-md-editor').then((mod) => mod.default),
  { ssr: false }
)

export interface MarkdownEditorProps {
  value?: string
  onChange?: (value?: string) => void
  placeholder?: string
  height?: number
  preview?: 'live' | 'edit' | 'preview'
  hideToolbar?: boolean
  textareaId?: string
  name?: string
  className?: string
}

export const MarkdownEditor = forwardRef<HTMLDivElement, MarkdownEditorProps>(
  ({ value = '', onChange, placeholder, height = 300, preview = 'live', hideToolbar = false, className, textareaId, name }, ref) => {
    return (
      <div className={className} ref={ref}>
        <MDEditor
          value={value}
          onChange={onChange}
          preview={preview}
          height={height}
          hideToolbar={hideToolbar}
          textareaProps={{
            placeholder: placeholder || 'Enter markdown...',
            id: textareaId,
            name: name,
          }}
          previewOptions={{
            remarkPlugins: [remarkMath],
            rehypePlugins: [rehypeKatex],
          }}
          data-color-mode="light"
        />
      </div>
    )
  }
)

MarkdownEditor.displayName = 'MarkdownEditor'