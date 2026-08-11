import type { Metadata } from "next";
import { DM_Sans, DM_Mono, Cormorant_Garamond, Pacifico, Space_Grotesk, Instrument_Serif } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { PostHogProvider } from "@/components/posthog-provider";
import { ToastProvider } from "@/components/ui/toast";
import "./globals.css";
import {
  RUNTIME_CONFIG_SCRIPT_ID,
  runtimeConfigScript,
  serverRuntimeConfig,
} from "@/lib/runtime-config";

const dmSans = DM_Sans({
  variable: "--font-dm-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const dmMono = DM_Mono({
  variable: "--font-dm-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

const cormorantGaramond = Cormorant_Garamond({
  variable: "--font-cormorant",
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
});

const pacifico = Pacifico({
  variable: "--font-pacifico",
  subsets: ["latin"],
  weight: "400",
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  variable: "--font-instrument-serif",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("http://localhost:3000"),
  title: {
    default: "OpenRecruiting. Structured interview feedback in under a minute.",
    template: "%s | OpenRecruiting",
  },
  description:
    "AI-powered interview copilot for structured interviews. Get real-time guidance, auto-generated feedback, and hiring insights. Transform your recruitment process with OpenRecruiting.",
  keywords: [
    "interview intelligence",
    "AI interview copilot",
    "structured interviews",
    "interview feedback",
    "recruitment AI",
    "hiring platform",
    "interview automation",
    "candidate evaluation",
  ],
  authors: [{ name: "OpenRecruiting", url: "http://localhost:3000" }],
  creator: "OpenRecruiting",
  publisher: "OpenRecruiting",
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "http://localhost:3000",
    siteName: "OpenRecruiting",
    title: "OpenRecruiting. Structured interview feedback in under a minute.",
    description:
      "AI-powered interview copilot for structured interviews. Real-time guidance, auto-generated feedback, and hiring insights.",
  },
  twitter: {
    card: "summary_large_image",
    title: "OpenRecruiting. Structured interview feedback in under a minute.",
    description:
      "AI-powered interview copilot for structured interviews. Real-time guidance, auto-generated feedback, and hiring insights.",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  alternates: {
    canonical: "http://localhost:3000",
  },
};

/**
 * Render every route per request. Load-bearing: without it Next prerenders the
 * shell at BUILD time and freezes window.__OR_CONFIG__ into static HTML with
 * empty values — the same build-time-baking bug relocated from the JS bundle
 * to the HTML. See src/lib/runtime-config.ts.
 *
 * Next 16: `dynamic` is documented under the previous caching model and is
 * removed when cacheComponents is enabled, but every page is dynamic by
 * default under that model, so the requirement holds either way. Remove it as
 * part of THAT migration, not on its own.
 */
export const dynamic = 'force-dynamic';

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html id="root-html" lang="en" suppressHydrationWarning>
      <head>
        {/* MUST stay first: client code reads window.__OR_CONFIG__ before hydration. */}
        <script
          id={RUNTIME_CONFIG_SCRIPT_ID}
          dangerouslySetInnerHTML={{ __html: runtimeConfigScript(serverRuntimeConfig()) }}
        />
        <link rel="dns-prefetch" href="https://us.i.posthog.com" />
        <link rel="dns-prefetch" href="https://us-assets.i.posthog.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="preconnect" href="https://i.ytimg.com" crossOrigin="anonymous" />
      </head>
      <body
        className={`${dmSans.variable} ${dmMono.variable} ${cormorantGaramond.variable} ${spaceGrotesk.variable} ${pacifico.variable} ${instrumentSerif.variable} antialiased font-sans`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem={false}
          disableTransitionOnChange
        >
          <PostHogProvider>
            <ToastProvider>
              {children}
            </ToastProvider>
          </PostHogProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
