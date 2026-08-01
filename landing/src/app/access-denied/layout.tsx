import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Access denied | OpenRecruiting",
  robots: { index: false, follow: false },
};

export default function AccessDeniedLayout({ children }: { children: React.ReactNode }) {
  return children;
}
