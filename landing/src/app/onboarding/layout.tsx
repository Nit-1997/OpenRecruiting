import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "See How OpenRecruiting Works",
  description:
    "Experience OpenRecruiting with an interactive demo. See how AI-powered interview intelligence works with structured interviews, real-time guidance, and instant feedback.",
};

export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
