"use client";

import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAnalytics } from "@/hooks/useAnalytics";

interface Plan {
  id: string;
  key: string;
  name: string;
  priceCents: number;
  period: string;
  description: string;
  features: string[];
  cta: string;
  highlighted: boolean;
  isEnterprise?: boolean;
}

const plans: Plan[] = [
  {
    id: "pricing-free",
    key: "free",
    name: "Free",
    priceCents: 0,
    period: "",
    description: "Try OpenRecruiting with a free intake call and interview to experience AI-powered hiring.",
    features: [
      "1 intake call per month",
      "1 interview per month",
      "AI-generated feedback reports",
      "Personal workspace",
    ],
    cta: "Get Started",
    highlighted: false,
  },
  {
    id: "pricing-individual",
    key: "individual",
    name: "Individual",
    priceCents: 2900,
    period: "/month",
    description: "For independent recruiters and hiring managers ready to scale their hiring.",
    features: [
      "Unlimited intake calls",
      "10 interviews per month",
      "AI-generated feedback reports",
    ],
    cta: "Get Started",
    highlighted: true,
  },
  {
    id: "pricing-enterprise",
    key: "enterprise",
    name: "Enterprise",
    priceCents: -1,
    period: "",
    description: "For teams that need custom solutions, shared pipelines, and dedicated support.",
    features: [
      "Unlimited intake calls",
      "Unlimited interviews",
      "Everything in Individual",
      "Custom seat count",
      "Shared candidate pipelines",
      "Dedicated account manager",
      "SLA guarantee",
    ],
    cta: "Contact Us",
    highlighted: false,
    isEnterprise: true,
  },
];

const containerVariants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.12 },
  },
};

const cardVariants = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

function PricingSection() {
  const router = useRouter();
  const { trackEvent } = useAnalytics();

  const handlePlanClick = (plan: Plan) => {
    trackEvent("pricing_plan_clicked", { plan: plan.key });
    // The Enterprise CTA used to open the demo modal, which is gone. Sign-in is
    // the only real destination the landing site has today — there is no
    // /contact route. Point this at one when there is.
    if (plan.isEnterprise) {
      router.push("/login");
      return;
    }
    if (plan.key === "free") {
      router.push("/login");
    } else {
      router.push(`/login?redirect=/dashboard/billing`);
    }
  };

  const getDisplayPrice = (plan: Plan): { original: string | null; current: string } => {
    if (plan.isEnterprise) {
      return { original: null, current: "Custom" };
    }
    if (plan.priceCents === 0) {
      return { original: null, current: "$0" };
    }
    return { original: null, current: `$${plan.priceCents / 100}` };
  };

  return (
    <>
    <section id="pricing-section" className="pt-28 md:pt-32 pb-12 md:pb-16 relative overflow-hidden">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/Pricing-Image.png"
        alt=""
        className="absolute inset-0 w-full h-full object-cover z-0"
      />

      <div id="pricing-inner" className="max-w-[1100px] mx-auto px-6 relative z-10">
        <h2
          id="pricing-title"
          className="font-display text-4xl md:text-5xl font-light text-white text-center mb-10 relative z-30 drop-shadow-[0_2px_8px_rgba(0,0,0,0.3)]"
        >
          Simple, transparent pricing
        </h2>

        <motion.div
          id="pricing-cards"
          className="grid grid-cols-1 md:grid-cols-3 gap-5"
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
        >
          {plans.map((plan) => {
            const { original, current } = getDisplayPrice(plan);

            return (
              <motion.div
                key={plan.id}
                id={plan.id}
                className={`relative rounded-2xl p-7 flex flex-col ${
                  plan.highlighted
                    ? "bg-[#111111] text-white border-2 border-[#111111]"
                    : "bg-[#FAF9F7] border border-[#E5E3DF]"
                }`}
                variants={cardVariants}
              >
                {plan.highlighted && (
                  <span
                    id="pricing-popular-badge"
                    className="absolute -top-3 left-1/2 -translate-x-1/2 bg-primary text-white text-xs font-medium px-3 py-1 rounded-full"
                  >
                    Most Popular
                  </span>
                )}

                <h3
                  id={`${plan.id}-name`}
                  className={`font-display text-lg font-medium mb-1 ${
                    plan.highlighted ? "text-white" : "text-[var(--lp-text-primary)]"
                  }`}
                >
                  {plan.name}
                </h3>

                <div id={`${plan.id}-price`} className="flex items-baseline gap-2 mb-3">
                  {original && (
                    <span
                      id={`${plan.id}-original-price`}
                      className={`text-xl line-through ${
                        plan.highlighted ? "text-white/40" : "text-[var(--lp-text-muted)]"
                      }`}
                    >
                      {original}
                    </span>
                  )}
                  <span
                    id={`${plan.id}-current-price`}
                    className={`text-4xl font-display font-normal ${
                      plan.highlighted ? "text-white" : "text-[var(--lp-text-primary)]"
                    }`}
                  >
                    {current}
                  </span>
                  {plan.period && (
                    <span
                      id={`${plan.id}-period`}
                      className={`text-sm ${
                        plan.highlighted ? "text-white/60" : "text-[var(--lp-text-muted)]"
                      }`}
                    >
                      {plan.period}
                    </span>
                  )}
                </div>

                <p
                  id={`${plan.id}-desc`}
                  className={`text-sm leading-relaxed mb-6 ${
                    plan.highlighted ? "text-white/70" : "text-[var(--lp-text-secondary)]"
                  }`}
                >
                  {plan.description}
                </p>

                <ul id={`${plan.id}-features`} className="space-y-3 mb-8 flex-1">
                  {plan.features.map((feature, i) => (
                    <li
                      key={i}
                      id={`${plan.id}-feature-${i}`}
                      className="flex items-start gap-2.5 text-sm"
                    >
                      <Check
                        className={`w-4 h-4 mt-0.5 flex-shrink-0 ${
                          plan.highlighted ? "text-primary" : "text-primary"
                        }`}
                      />
                      <span
                        className={
                          plan.highlighted ? "text-white/90" : "text-[var(--lp-text-secondary)]"
                        }
                      >
                        {feature}
                      </span>
                    </li>
                  ))}
                </ul>

                <Button
                  id={`${plan.id}-cta`}
                  onClick={() => handlePlanClick(plan)}
                  className={`w-full h-12 rounded-full text-base font-medium ${
                    plan.highlighted
                      ? "bg-white text-[#111111] hover:bg-white/90"
                      : "bg-[#111111] text-white hover:bg-[#111111]/90"
                  }`}
                >
                  {plan.cta}
                </Button>
              </motion.div>
            );
          })}
        </motion.div>

        <p
          id="pricing-subtitle"
          className="font-display text-sm md:text-base font-light text-white/80 text-center max-w-xl mx-auto mt-8 relative z-20 drop-shadow-[0_2px_8px_rgba(0,0,0,0.3)]"
        >
          Start free, upgrade anytime. No hidden fees, no long-term contracts.
        </p>
      </div>
    </section>
    </>
  );
}

export { PricingSection };
