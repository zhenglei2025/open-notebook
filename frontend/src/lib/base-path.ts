const rawBasePath = process.env.NEXT_PUBLIC_BASE_PATH || ''

export function normalizeBasePath(basePath?: string | null): string {
  if (!basePath) {
    return ''
  }

  const trimmed = basePath.trim()
  if (!trimmed || trimmed === '/') {
    return ''
  }

  const withLeadingSlash = trimmed.startsWith('/') ? trimmed : `/${trimmed}`
  return withLeadingSlash.replace(/\/+$/, '')
}

export function getBasePath(): string {
  return normalizeBasePath(rawBasePath)
}

export function withBasePath(path: string): string {
  const basePath = getBasePath()

  if (!path) {
    return basePath || '/'
  }

  if (
    path.startsWith('http://') ||
    path.startsWith('https://') ||
    path.startsWith('//') ||
    path.startsWith('mailto:') ||
    path.startsWith('tel:') ||
    path.startsWith('#')
  ) {
    return path
  }

  const normalizedPath = path.startsWith('/') ? path : `/${path}`

  if (!basePath) {
    return normalizedPath
  }

  if (normalizedPath === basePath || normalizedPath.startsWith(`${basePath}/`)) {
    return normalizedPath
  }

  return `${basePath}${normalizedPath}`
}
