import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('base path helpers', () => {
  const originalEnv = process.env

  beforeEach(() => {
    vi.resetModules()
    process.env = { ...originalEnv }
  })

  afterEach(() => {
    process.env = originalEnv
  })

  it('normalizes empty or root values to an empty base path', async () => {
    const { normalizeBasePath } = await import('./base-path')

    expect(normalizeBasePath('')).toBe('')
    expect(normalizeBasePath('/')).toBe('')
    expect(normalizeBasePath(undefined)).toBe('')
  })

  it('normalizes subdirectory values with a leading slash and no trailing slash', async () => {
    const { normalizeBasePath } = await import('./base-path')

    expect(normalizeBasePath('tools/notebook')).toBe('/tools/notebook')
    expect(normalizeBasePath('/tools/notebook/')).toBe('/tools/notebook')
  })

  it('returns unchanged root-relative paths when no base path is configured', async () => {
    delete process.env.NEXT_PUBLIC_BASE_PATH

    const { getBasePath, withBasePath } = await import('./base-path')

    expect(getBasePath()).toBe('')
    expect(withBasePath('/config')).toBe('/config')
    expect(withBasePath('/sources/123')).toBe('/sources/123')
  })

  it('prefixes app-relative paths when a base path is configured', async () => {
    process.env.NEXT_PUBLIC_BASE_PATH = '/tools/notebook'

    const { getBasePath, withBasePath } = await import('./base-path')

    expect(getBasePath()).toBe('/tools/notebook')
    expect(withBasePath('/config')).toBe('/tools/notebook/config')
    expect(withBasePath('/sources/123')).toBe('/tools/notebook/sources/123')
    expect(withBasePath('/tools/notebook/config')).toBe('/tools/notebook/config')
  })
})
