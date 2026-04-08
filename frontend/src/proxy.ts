import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { getBasePath, withBasePath } from '@/lib/base-path'

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl
  const basePath = getBasePath()

  // Redirect root to notebooks
  if (pathname === '/' || (basePath && (pathname === basePath || pathname === `${basePath}/`))) {
    const url = request.nextUrl.clone()
    url.pathname = withBasePath('/notebooks')
    return NextResponse.redirect(url)
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    '/((?!api|_next/static|_next/image|favicon.ico).*)',
  ],
}
