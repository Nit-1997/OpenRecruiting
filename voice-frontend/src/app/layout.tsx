import type { Metadata } from "next";
import { Geist, Geist_Mono, Pacifico } from "next/font/google";
import "./globals.css";
import {
  RUNTIME_CONFIG_SCRIPT_ID,
  runtimeConfigScript,
  serverRuntimeConfig,
} from "@/lib/runtime-config";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const pacifico = Pacifico({
  weight: "400",
  variable: "--font-pacifico",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Scout Voice Agent",
  description: "Real-time voice feedback collection agent",
};

/**
 * Render every route per request. Load-bearing: without it Next prerenders
 * the shell at BUILD time and freezes window.__OR_CONFIG__ into static HTML
 * with empty values, which is the same build-time-baking bug relocated from
 * the JS bundle to the HTML. See src/lib/runtime-config.ts.
 *
 * Next 16 note: `dynamic` is documented under the previous caching model and
 * is removed when cacheComponents is enabled — but under that model every
 * page is dynamic by default, so the requirement holds either way. Remove it
 * as part of THAT migration, not on its own.
 */
export const dynamic = 'force-dynamic';

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html id="root-html" lang="en">
      <head>
        {/* MUST stay first: client code reads window.__OR_CONFIG__ before hydration. */}
        <script
          id={RUNTIME_CONFIG_SCRIPT_ID}
          dangerouslySetInnerHTML={{ __html: runtimeConfigScript(serverRuntimeConfig()) }}
        />
      </head>
      <body
        id="root-body"
        className={`${geistSans.variable} ${geistMono.variable} ${pacifico.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
