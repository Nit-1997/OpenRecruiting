import type { Metadata } from 'next';
import { DM_Mono, DM_Sans, Instrument_Serif, Pacifico } from 'next/font/google';
import './globals.css';
import { V2Bootstrap } from '@/lib/v2-bootstrap';
import { cn } from '@/lib/utils';

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
        <script
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
