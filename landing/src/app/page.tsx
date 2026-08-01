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

const SocialProofSection = dynamic(
  () => import("@/components/ui/social-proof-section").then((mod) => ({ default: mod.SocialProofSection })),
  { loading: () => <div id="social-proof-skeleton" className="min-h-[400px]" /> },
);

const ProductShowcase = dynamic(
  () => import("@/components/ui/product-showcase").then((mod) => ({ default: mod.ProductShowcase })),
  { loading: () => <div id="product-showcase-skeleton" className="min-h-[500px]" /> },
);

const IntegrationsHub = dynamic(
  () => import("@/components/ui/integrations-hub").then((mod) => ({ default: mod.IntegrationsHub })),
  { loading: () => <div id="integrations-hub-skeleton" className="min-h-[400px]" /> },
);

const CTASection = dynamic(
  () => import("@/components/ui/cta-section").then((mod) => ({ default: mod.CTASection })),
  { loading: () => <div id="cta-skeleton" className="min-h-[300px]" /> },
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
        <SocialProofSection />
        <ProductShowcase />
        <IntegrationsHub />
        <CTASection />
      </main>
      <Footer />
    </div>
  );
}
