import type { Metadata } from "next";
import { Space_Grotesk, Geist_Mono, Pacifico } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import "./globals.css";
import {
  RUNTIME_CONFIG_SCRIPT_ID,
  runtimeConfigScript,
  serverRuntimeConfig,
} from "@/lib/runtime-config";

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const pacifico = Pacifico({
  variable: "--font-pacifico",
  subsets: ["latin"],
  weight: "400",
});

export const metadata: Metadata = {
  title: "OpenRecruiting Admin - Customer Onboarding",
  description: "Admin dashboard for customer onboarding and requisition management",
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
      </head>
      <body
        id="root-body"
        className={`${spaceGrotesk.variable} ${geistMono.variable} ${pacifico.variable} antialiased font-sans`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem={false}
          disableTransitionOnChange
        >
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
