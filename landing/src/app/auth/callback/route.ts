import { serverBackendUrl } from '@/lib/backend-url'
import { createClient } from '@/lib/supabase/server'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get('code')

  if (code) {
    const supabase = await createClient()
    const { data, error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error && data.session) {
      const user = data.session.user
      const provider = user?.app_metadata?.provider || 'email'
      const isGoogleUser = provider === 'google'
      const needsPassword = !isGoogleUser && !user?.user_metadata?.password_set

      const cookieStore = await cookies()
      const savedRedirect = cookieStore.get('auth_redirect')?.value
      const appUrl = process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3005'

      if (needsPassword) {
        return NextResponse.redirect(`${origin}/set-password`)
      }

      let redirectTo = `${appUrl}/dashboard`
      if (savedRedirect) {
        const decoded = decodeURIComponent(savedRedirect)
        if (decoded.startsWith('/') && !decoded.startsWith('//')) {
          redirectTo = decoded.startsWith('/dashboard') ? `${appUrl}${decoded}` : `${origin}${decoded}`
        }
        cookieStore.delete('auth_redirect')
      }

      // Always call complete-signup so the backend gate applies to all providers.
      // The endpoint is idempotent: existing profiles return is_new:false.
      // This route runs IN THE CONTAINER, so it cannot use the browser's
      // NEXT_PUBLIC_API_V2_URL (http://localhost:8004 — the container itself).
      // The fetch below fails closed, so getting this wrong did not leak access:
      // it signed every Google user straight back out with "Sign-in is
      // temporarily unavailable", which reads like an outage rather than config.
      const apiUrl = serverBackendUrl()

      // Sign-out helper: clears the session cookie before redirecting away.
      // Best-effort signOut PLUS explicit cookie deletion so a signOut failure
      // can't leave a valid session cookie attached to the redirect.
      const signOutAndRedirect = async (target: string) => {
        try {
          await supabase.auth.signOut()
        } catch (e) {
          console.error('signOut failed before redirect:', e)
        }
        try {
          cookieStore.delete('openrecruiting-auth')
        } catch (e) {
          console.error('cookie delete failed before redirect:', e)
        }
        return NextResponse.redirect(target)
      }

      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 5000)
      let signupRes: Response
      try {
        signupRes = await fetch(`${apiUrl}/api/v2/auth/complete-signup`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${data.session.access_token}`,
            'Content-Type': 'application/json',
          },
          signal: controller.signal,
        })
      } catch (e) {
        // Network error, timeout, or abort. Fail closed — backend gate is the
        // single source of truth for sign-up authorization, so any inability to
        // reach it must NOT admit the user to the dashboard.
        console.error('complete-signup fetch failed:', e)
        return signOutAndRedirect(`${origin}/login?error=auth_unavailable`)
      } finally {
        clearTimeout(timeout)
      }

      if (signupRes.status === 403) {
        const body = await signupRes.json().catch(() => null) as { detail?: { code?: string } } | null
        if (body?.detail?.code === 'signup_blocked') {
          // Confirmed gate rejection — go to the friendly access-denied page.
          return signOutAndRedirect(`${origin}/access-denied`)
        }
        // Unexpected 403 shape — treat as unavailable rather than admit.
        console.error('complete-signup unexpected 403:', body)
        return signOutAndRedirect(`${origin}/login?error=auth_unavailable`)
      }

      if (!signupRes.ok) {
        // 4xx or 5xx other than the signup_blocked 403. Fail closed.
        console.error('complete-signup non-ok response:', signupRes.status)
        return signOutAndRedirect(`${origin}/login?error=auth_unavailable`)
      }

      // 2xx — proceed to the dashboard via the existing redirect.
      return NextResponse.redirect(redirectTo)
    }
  }

  return NextResponse.redirect(`${origin}/login?error=auth_failed`)
}
