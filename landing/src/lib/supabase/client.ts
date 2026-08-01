import { createBrowserClient } from "@supabase/ssr"

const COOKIE_NAME = "openrecruiting-auth"

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      auth: {
        storageKey: COOKIE_NAME,
      },
      cookieOptions: {
        name: COOKIE_NAME,
        domain: process.env.NEXT_PUBLIC_COOKIE_DOMAIN || undefined,
      }
    }
  )
}
