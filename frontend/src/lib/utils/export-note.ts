/**
 * Export utilities for converting notes to PDF and Word.
 * Grabs the rendered HTML directly from the editor's preview pane
 * so the export matches exactly what the user sees.
 */

/**
 * Get the rendered preview HTML from the editor's DOM.
 * Falls back to basic markdown if the preview pane is not found.
 */
function getPreviewHtml(): string | null {
  // @uiw/react-md-editor renders preview in .wmde-markdown
  const previewEl = document.querySelector('.wmde-markdown')
  if (previewEl) {
    return previewEl.innerHTML
  }
  // Fallback: try w-md-editor-preview
  const altPreview = document.querySelector('.w-md-editor-preview')
  if (altPreview) {
    return altPreview.innerHTML
  }
  return null
}

/**
 * Get the editor's preview styles from current page stylesheets.
 */
function getEditorStyles(): string {
  const styles: string[] = []
  try {
    for (const sheet of Array.from(document.styleSheets)) {
      try {
        const rules = sheet.cssRules || sheet.rules
        for (const rule of Array.from(rules)) {
          const text = rule.cssText
          // Grab styles relevant to markdown rendering
          if (
            text.includes('wmde-markdown') ||
            text.includes('markdown-body') ||
            text.includes('.w-md-editor')
          ) {
            styles.push(text)
          }
        }
      } catch {
        // Cross-origin stylesheets will throw, skip them
      }
    }
  } catch {
    // Ignore errors
  }
  return styles.join('\n')
}

/**
 * Build a full HTML document for export with proper styling.
 */
function buildExportHtml(contentHtml: string, title?: string): string {
  const editorStyles = getEditorStyles()
  const titleHtml = title ? `<h1 class="export-title">${title}</h1>` : ''

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  /* Base styles */
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", "Noto Sans SC", Helvetica, Arial, sans-serif;
    max-width: 900px;
    margin: 0 auto;
    padding: 40px;
    line-height: 1.6;
    color: #24292f;
    font-size: 14px;
  }
  .export-title {
    text-align: center;
    font-size: 24px;
    margin-bottom: 24px;
    padding-bottom: 12px;
    border-bottom: 2px solid #d0d7de;
  }

  /* Markdown content styles (matching GitHub-style) */
  h1 { font-size: 2em; margin: 0.67em 0; padding-bottom: 0.3em; border-bottom: 1px solid #d0d7de; }
  h2 { font-size: 1.5em; margin: 0.83em 0; padding-bottom: 0.3em; border-bottom: 1px solid #d0d7de; }
  h3 { font-size: 1.25em; margin: 1em 0; }
  h4 { font-size: 1em; margin: 1.33em 0; }
  p { margin: 0 0 16px; }
  
  /* Tables */
  table {
    border-collapse: collapse;
    border-spacing: 0;
    width: 100%;
    margin: 16px 0;
    display: table !important;
  }
  th, td {
    border: 1px solid #d0d7de;
    padding: 6px 13px;
    text-align: left;
  }
  th {
    font-weight: 600;
    background-color: #f6f8fa;
  }
  tr:nth-child(even) {
    background-color: #f6f8fa;
  }

  /* Code */
  code {
    background-color: rgba(175,184,193,0.2);
    padding: 0.2em 0.4em;
    border-radius: 6px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 85%;
  }
  pre {
    background: #f6f8fa;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    padding: 16px;
    overflow-x: auto;
    margin: 16px 0;
  }
  pre code {
    background: none;
    padding: 0;
    border-radius: 0;
    font-size: 85%;
    line-height: 1.45;
  }

  /* Blockquotes */
  blockquote {
    border-left: 4px solid #d0d7de;
    color: #656d76;
    margin: 0 0 16px;
    padding: 0 1em;
  }

  /* Lists */
  ul, ol { padding-left: 2em; margin: 0 0 16px; }
  li { margin: 4px 0; }
  li + li { margin-top: 0.25em; }

  /* Horizontal rules */
  hr { border: none; border-top: 1px solid #d0d7de; margin: 24px 0; }

  /* Links */
  a { color: #0969da; text-decoration: none; }

  /* Images */
  img { max-width: 100%; }

  /* Editor-specific styles from page */
  ${editorStyles}

  /* Print optimizations */
  @media print {
    body { padding: 20px; max-width: none; }
    pre { white-space: pre-wrap; word-wrap: break-word; }
    table { page-break-inside: avoid; }
  }
</style>
</head>
<body>
${titleHtml}
<div class="wmde-markdown markdown-body">
${contentHtml}
</div>
</body>
</html>`
}

/**
 * Export note as PDF using browser print dialog.
 * Grabs rendered HTML from the editor preview for exact visual match.
 */
export function exportToPdf(content: string, title?: string): void {
  const previewHtml = getPreviewHtml()
  if (!previewHtml) {
    alert('Please switch editor to preview or live mode to export PDF')
    return
  }

  // Clean citation markers from export
  const cleanedHtml = previewHtml.replace(/\[(source|note|insight):[^\]]+\]/g, '')

  const fullHtml = buildExportHtml(cleanedHtml, title)
  const printWindow = window.open('', '_blank')
  if (!printWindow) {
    alert('Please allow pop-ups to export PDF')
    return
  }
  printWindow.document.write(fullHtml)
  printWindow.document.close()
  // Single print trigger with delay for rendering
  setTimeout(() => {
    printWindow.print()
  }, 800)
}

/**
 * Export note as HTML in a new browser tab.
 * Same as PDF but without triggering the print dialog.
 */
export function exportToHtml(content: string, title?: string): void {
  const previewHtml = getPreviewHtml()
  if (!previewHtml) {
    alert('Please switch editor to preview or live mode to export HTML')
    return
  }

  // Clean citation markers from export
  const cleanedHtml = previewHtml.replace(/\[(source|note|insight):[^\]]+\]/g, '')

  const fullHtml = buildExportHtml(cleanedHtml, title)
  const htmlWindow = window.open('', '_blank')
  if (!htmlWindow) {
    alert('Please allow pop-ups to export HTML')
    return
  }
  htmlWindow.document.write(fullHtml)
  htmlWindow.document.close()
}

/**
 * Export note as Word (.doc) using HTML blob.
 * Grabs rendered HTML from the editor preview for exact visual match.
 */
export function exportToWord(content: string, title?: string): void {
  const previewHtml = getPreviewHtml()
  if (!previewHtml) {
    alert('Please switch editor to preview or live mode to export Word')
    return
  }

  // Clean citation markers from export
  const cleanedHtml = previewHtml.replace(/\[(source|note|insight):[^\]]+\]/g, '')

  const wordHtml = `<html xmlns:o="urn:schemas-microsoft-com:office:office" 
        xmlns:w="urn:schemas-microsoft-com:office:word" 
        xmlns="http://www.w3.org/TR/REC-html40">
<head>
  <meta charset="utf-8">
  <meta name="ProgId" content="Word.Document">
  <style>
    body {
      font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", SimSun, sans-serif;
      line-height: 1.8;
      color: #333;
      font-size: 12pt;
    }
    h1 { font-size: 18pt; margin: 16pt 0 8pt; }
    h2 { font-size: 16pt; margin: 14pt 0 7pt; }
    h3 { font-size: 14pt; margin: 12pt 0 6pt; }
    h4 { font-size: 12pt; margin: 10pt 0 5pt; font-weight: bold; }
    p { margin: 6pt 0; }
    code {
      background: #f4f4f4;
      padding: 1pt 4pt;
      font-family: "Courier New", monospace;
      font-size: 10pt;
    }
    pre {
      background: #f8f8f8;
      border: 1px solid #ddd;
      padding: 10pt;
      font-family: "Courier New", monospace;
      font-size: 10pt;
    }
    blockquote {
      border-left: 3pt solid #ddd;
      padding: 6pt 12pt;
      margin: 8pt 0;
      color: #666;
    }
    table { border-collapse: collapse; width: 100%; margin: 8pt 0; }
    th, td { border: 1px solid #999; padding: 6pt 10pt; text-align: left; }
    th { background: #f0f0f0; font-weight: bold; }
    ul, ol { padding-left: 20pt; }
    li { margin: 3pt 0; }
  </style>
</head>
<body>
  ${title ? `<h1 style="text-align:center">${title}</h1>` : ''}
  ${cleanedHtml}
</body>
</html>`

  const blob = new Blob(['\ufeff' + wordHtml], { type: 'application/msword' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${title || 'note'}.doc`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
