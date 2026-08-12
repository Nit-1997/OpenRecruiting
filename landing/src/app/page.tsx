import type { Metadata } from "next";
import dynamic from "next/dynamic";
import { Header } from "@/components/ui/header";
import { Hero } from "@/components/ui/animated-hero";
import { Footer } from "@/components/ui/footer";

const IntegrationBar = dynamic(
  () => import("@/components/ui/integration-bar").then((mod) => ({ default: mod.IntegrationBar })),
  { loading: () => <div id="integration-bar-skeleton" className="min-h-[160px]" /> },
);

const FromPlanToDecision = dynamic(
  () => import("@/components/ui/from-plan-to-decision").then((mod) => ({ default: mod.FromPlanToDecision })),
  { loading: () => <div id="from-plan-skeleton" className="min-h-[500px]" /> },
);

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

const IntegrationsHub = dynamic(
  () => import("@/components/ui/integrations-hub").then((mod) => ({ default: mod.IntegrationsHub })),
  { loading: () => <div id="integrations-hub-skeleton" className="min-h-[400px]" /> },
);

export const metadata: Metadata = {
  alternates: { canonical: "http://localhost:3000" },
};

const organizationJsonLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "OpenRecruiting",
  url: "http://localhost:3000",
  logo: "http://localhost:3000/icon.svg",
  description:
    "AI-powered interview intelligence platform for structured interviews, real-time guidance, and automated feedback.",
};

const softwareJsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "OpenRecruiting",
  url: "http://localhost:3000",
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  description:
    "Interview intelligence platform that provides real-time interview guidance, structured interview templates, and AI-generated candidate feedback.",
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "USD",
  },
};

export default function Home() {
  return (
    <div id="landing-page" className="landing-page min-h-screen">
      <script
        id="jsonld-organization"
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(organizationJsonLd) }}
      />
      <script
        id="jsonld-software"
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(softwareJsonLd) }}
      />
      <Header variant="light" />
      <main id="main-content" className="relative z-0">
        <Hero />
        <IntegrationBar />
        <FromPlanToDecision />
        {/* Cortex used to be its own page. It is the second half of the same
            story — what the captured signal becomes — so it lives here now,
            in the slot the product video occupied. #cortex anchors to it. */}
        <div id="cortex">
          <CortexKnowledgeGraph />
          <CortexHowItWorks />
          <CortexCapabilities />
        </div>
        <IntegrationsHub />
      </main>
      <Footer />
    </div>
  );
}
