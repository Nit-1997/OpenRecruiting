import { createBrowserClient } from "@supabase/ssr"
import { getRuntimeConfig } from "@/lib/runtime-config";

export function createClient() {
  return createBrowserClient(
    getRuntimeConfig().supabaseUrl,
    getRuntimeConfig().supabaseAnonKey,
    {
      auth: {
        storageKey: 'openrecruiting-admin-auth',
      },
      cookieOptions: {
        name: 'openrecruiting-admin-auth',
      }
    }
  )
}
