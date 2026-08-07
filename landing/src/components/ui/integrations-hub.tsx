"use client";

import { motion } from "framer-motion";
import Image from "next/image";

const CATEGORIES = [
  {
    label: "Video",
    items: [
      { name: "Google Meet", icon: "/logos/google_meet_horizontal_wordmark_2020q4_2x_icon_124_40_292e71bcb52a56e2a9005164118f183b.png" },
      { name: "Zoom", icon: "/logos/zoom.webp" },
      { name: "Teams", icon: "/logos/microsoft-teams-icon-logo-symbol-free-png.webp" },
    ],
  },
  {
    label: "Communication",
    items: [
      { name: "Slack", icon: "/logos/slack.webp" },
      { name: "Gmail", icon: "/logos/gmail-icon-free-png.webp" },
      { name: "Outlook", icon: "/logos/microsoft_outlook_alt_macos_bigsur_icon_189970.webp" },
    ],
  },
  {
    label: "ATS",
    items: [
      { name: "Greenhouse", icon: "/logos/greenhouse.webp" },
      { name: "Ashby", icon: "/logos/ashbyhq.webp" },
    ],
  },
];

function IntegrationsHub() {
  return (
    <section id="integrations-hub" className="py-12 md:py-16 bg-[var(--lp-bg)]">
      <div className="max-w-[960px] mx-auto px-6">
        <motion.h2
          className="font-display text-3xl md:text-4xl font-light text-[var(--lp-text-primary)] text-center mb-10"
          initial={{ opacity: 0, y: 15 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.4 }}
        >
          We work where you are
        </motion.h2>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-6 md:gap-8">
          {CATEGORIES.map((cat, ci) => (
            <motion.div
              key={cat.label}
              className="text-center"
              initial={{ opacity: 0, y: 10 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.3, delay: ci * 0.08 }}
            >
              <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-[var(--lp-text-muted)] mb-3">{cat.label}</p>
              <div className="flex items-center justify-center gap-3 flex-wrap">
                {cat.items.map((item) => (
                  <div key={item.name} className="relative group w-10 h-10 rounded-xl bg-white border border-[#E5E3DF] shadow-sm flex items-center justify-center hover:shadow-md hover:scale-110 transition-all cursor-default">
                    <Image src={item.icon} alt={item.name} width={24} height={24} className="object-contain" />
                    <span className="absolute -bottom-7 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded bg-[#111111] text-white text-[10px] font-medium whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                      {item.name}
                    </span>
                  </div>
                ))}
              </div>
            </motion.div>
          ))}
        </div>

        <p className="text-center text-sm text-[var(--lp-text-muted)] mt-8">
          & many more
        </p>
      </div>
    </section>
  );
}

export { IntegrationsHub };
