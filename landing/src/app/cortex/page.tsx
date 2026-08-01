import type { Metadata } from "next";
import dynamic from "next/dynamic";
import { Header } from "@/components/ui/header";
import { Footer } from "@/components/ui/footer";
import { CortexHero } from "@/components/ui/cortex-hero";

const CortexKnowledgeGraph = dynamic(
  () =>
    import("@/components/ui/cortex-knowledge-graph").then((mod) => ({
      default: mod.CortexKnowledgeGraph,
    })),
  { loading: () => <div id="cortex-graph-skeleton" className="min-h-[600px]" /> },
);

const CortexHowItWorks = dynamic(
  () =>
    import("@/components/ui/cortex-how-it-works").then((mod) => ({
      default: mod.CortexHowItWorks,
    })),
  { loading: () => <div id="cortex-how-skeleton" className="min-h-[600px]" /> },
);

const CortexCapabilities = dynamic(
  () =>
    import("@/components/ui/cortex-capabilities").then((mod) => ({
      default: mod.CortexCapabilities,
    })),
  { loading: () => <div id="cortex-capabilities-skeleton" className="min-h-[700px]" /> },
);

const CortexQuoteBand = dynamic(
  () => import("@/components/ui/cortex-cta").then((mod) => ({ default: mod.CortexQuoteBand })),
  { loading: () => <div id="cortex-quote-skeleton" className="min-h-[400px]" /> },
);

const CortexCTA = dynamic(
  () => import("@/components/ui/cortex-cta").then((mod) => ({ default: mod.CortexCTA })),
  { loading: () => <div id="cortex-cta-skeleton" className="min-h-[400px]" /> },
);

export const metadata: Metadata = {
  title: "OpenRecruiting Cortex — Hire with Evidence, Not Instinct",
  description:
    "Cortex is the intelligence layer for hiring: a living knowledge graph of every requisition, interview, and decision — queryable in plain English, with receipts.",
  alternates: { canonical: "http://localhost:3000/cortex" },
};

export default function CortexPage() {
  return (
    <div id="cortex-page" className="landing-page min-h-screen">
      <Header variant="light" />
      <main id="cortex-main" className="relative z-0">
        <CortexHero />
        <CortexKnowledgeGraph />
        <CortexQuoteBand />
        <CortexHowItWorks />
        <CortexCapabilities />
        <CortexCTA />
      </main>
      <Footer />
    </div>
  );
}
