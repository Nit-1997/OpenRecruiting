import { createBrowserClient } from "@supabase/ssr"
import { getRuntimeConfig } from "@/lib/runtime-config";

const COOKIE_NAME = "openrecruiting-auth"

export function createClient() {
  return createBrowserClient(
    getRuntimeConfig().supabaseUrl,
    getRuntimeConfig().supabaseAnonKey,
    {
      auth: {
        storageKey: COOKIE_NAME,
      },
      cookieOptions: {
        name: COOKIE_NAME,
        domain: getRuntimeConfig().cookieDomain || undefined,
      }
    }
  )
}
