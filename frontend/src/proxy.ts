import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { withBasePath } from '@/lib/base-path'

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Redirect only the bare root path so IP-based access can enter the app
  // without creating loops for the actual base path entrypoint.
  if (pathname === '/') {
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
