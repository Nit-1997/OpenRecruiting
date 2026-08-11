import type { Metadata } from 'next';
import { DM_Mono, DM_Sans, Instrument_Serif, Pacifico } from 'next/font/google';
import './globals.css';
import { V2Bootstrap } from '@/lib/v2-bootstrap';
import { cn } from '@/lib/utils';
import {
  RUNTIME_CONFIG_SCRIPT_ID,
  runtimeConfigScript,
  serverRuntimeConfig,
} from '@/lib/runtime-config';

const instrumentSerif = Instrument_Serif({
  subsets: ['latin'],
  weight: '400',
  style: ['normal', 'italic'],
  variable: '--font-instrument-serif',
  display: 'swap',
});

const dmSans = DM_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-dm-sans',
  display: 'swap',
});

const dmMono = DM_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-dm-mono',
  display: 'swap',
});

const pacifico = Pacifico({
  subsets: ['latin'],
  weight: '400',
  variable: '--font-pacifico',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'OpenRecruiting',
  description: 'The agentic recruiting workspace.',
};

/* Read the persisted theme and apply the `dark` class before React hydrates,
   so the html className matches what useThemeStore will set on the client.
   Without this, the Zustand persist rehydration adds `dark` after hydration
   and triggers a hydration mismatch on the <html> element. Mirrors the
   storage key + version used by src/stores/theme-store.ts.                  */
const themeBootstrap = `(() => {
  try {
    const raw = localStorage.getItem('openrecruiting.theme.v1');
    if (!raw) return;
    const parsed = JSON.parse(raw);
    const mode = parsed && parsed.state && parsed.state.mode;
    if (mode === 'dark') document.documentElement.classList.add('dark');
  } catch {}
})();`;

/**
 * Every route renders per request, and this is load-bearing — do not remove it
 * to "restore static optimisation".
 *
 * The layout injects window.__OR_CONFIG__ from process.env (see
 * src/lib/runtime-config.ts). Without this, Next prerenders the shell routes at
 * BUILD time and freezes that object into static HTML — with empty values, since
 * a build has no .env — so the browser would receive blanks no matter what the
 * running container's environment says. That is precisely the build-time-baking
 * bug the runtime config exists to fix, just relocated from the JS bundle to the
 * prerendered HTML. Verified: before this line, .next/server/app/login.html
 * shipped `window.__OR_CONFIG__={"supabaseUrl":"", ...}`.
 *
 * The cost is real but small here: this is an authenticated app whose middleware
 * already runs on every request, and no shell route can render meaningfully
 * without live config anyway.
 */
export const dynamic = 'force-dynamic';

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      id="root-html"
      lang="en"
      suppressHydrationWarning
      className={cn(
        instrumentSerif.variable,
        dmSans.variable,
        dmMono.variable,
        pacifico.variable,
        'font-sans',
      )}
    >
      <head>
        {/* MUST stay first: every client module reads window.__OR_CONFIG__ via
            getRuntimeConfig(), so it has to exist before hydration runs. These
            values are read from process.env at REQUEST time, which is what lets
            a container restart apply a changed .env without an image rebuild.
            See src/lib/runtime-config.ts. */}
        <script
          id={RUNTIME_CONFIG_SCRIPT_ID}
          // biome-ignore lint/security/noDangerouslySetInnerHtml: serialising server-resolved public config into the page is the mechanism itself; runtimeConfigScript escapes `<` so a value cannot close the tag
          dangerouslySetInnerHTML={{ __html: runtimeConfigScript(serverRuntimeConfig()) }}
        />
        <script
          id="theme-bootstrap"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: tiny inline boot script that runs before hydration to apply persisted dark mode
          dangerouslySetInnerHTML={{ __html: themeBootstrap }}
        />
      </head>
      <body id="root-body">
        <V2Bootstrap />
        {children}
      </body>
    </html>
  );
}
