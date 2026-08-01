"use client";

import { motion } from "framer-motion";

const cards = [
  {
    id: "why-openrecruiting-autonomous",
    title: "Autonomous",
    description:
      "AI plans your interviews, joins calls, and generates feedback — no manual effort required.",
  },
  {
    id: "why-openrecruiting-structured",
    title: "Structured",
    description:
      "Every interview follows a consistent, competency-based framework tailored to your role.",
  },
  {
    id: "why-openrecruiting-intelligent",
    title: "Intelligent",
    description:
      "Real-time analysis captures nuances that even experienced interviewers might miss.",
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

function WhyOpenRecruiting() {
  return (
    <section id="why-openrecruiting-section" className="py-20 md:py-28 bg-[var(--lp-bg)]">
      <div id="why-openrecruiting-inner" className="max-w-[960px] mx-auto px-6">
        <p
          id="why-openrecruiting-label"
          className="font-mono-label text-xs tracking-[0.2em] uppercase text-[var(--lp-text-muted)] text-center mb-4"
        >
          Why OpenRecruiting
        </p>
        <h2
          id="why-openrecruiting-title"
          className="font-display text-4xl md:text-5xl font-light text-[var(--lp-text-primary)] text-center mb-14"
        >
          Intelligence at every step
        </h2>

        <motion.div
          id="why-openrecruiting-cards"
          className="grid grid-cols-1 md:grid-cols-3 gap-5"
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
        >
          {cards.map((card) => (
            <motion.div
              key={card.id}
              id={card.id}
              className="bg-[var(--lp-surface)] border border-[var(--lp-border)] rounded-xl p-6 hover:-translate-y-1 transition-transform duration-200"
              variants={cardVariants}
            >
              <h3
                id={`${card.id}-title`}
                className="font-display text-lg font-medium text-[var(--lp-text-primary)] mb-2"
              >
                {card.title}
              </h3>
              <p
                id={`${card.id}-desc`}
                className="text-sm text-[var(--lp-text-secondary)] leading-relaxed"
              >
                {card.description}
              </p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}

export { WhyOpenRecruiting };
