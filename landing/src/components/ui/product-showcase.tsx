"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Play } from "lucide-react";
import Image from "next/image";

function ProductShowcase() {
  const [isPlaying, setIsPlaying] = useState(false);
  const videoId = "YNpwX3kpm6Y";

  return (
    <section
      id="product-showcase-section"
      className="py-20 md:py-28 relative overflow-hidden"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/see_in_action.png"
        alt=""
        className="absolute inset-0 w-full h-full object-cover z-0"
      />

      <div id="product-showcase-inner" className="max-w-[960px] mx-auto px-6 relative z-10">
        <motion.div
          id="product-showcase-header"
          className="text-center mb-12"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6 }}
        >
          <h2
            id="product-showcase-title"
            className="font-display text-4xl md:text-5xl font-light text-white mb-4"
          >
            See{" "}
            <span className="font-[family-name:var(--font-pacifico)]">
              openrecruiting<span className="text-white/60">.ai</span>
            </span>{" "}
            in Action
          </h2>
        </motion.div>

        <motion.div
          id="product-showcase-video"
          className="max-w-4xl mx-auto"
          initial={{ opacity: 0, y: 40 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6, delay: 0.2 }}
        >
          {/* Glassy video wrapper */}
          <div
            id="product-showcase-glassy-wrapper"
            className="rounded-3xl border border-white/20 bg-white/10 backdrop-blur-xl shadow-[0_8px_32px_rgba(0,0,0,0.2)] p-3 md:p-4"
          >
            <div
              id="product-showcase-iframe-wrapper"
              className="aspect-video rounded-2xl overflow-hidden"
            >
              {isPlaying ? (
                <iframe
                  id="product-showcase-iframe"
                  src={`https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0`}
                  title="OpenRecruiting Product Demo"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen
                  className="w-full h-full"
                />
              ) : (
                <button
                  id="product-showcase-play-btn"
                  type="button"
                  onClick={() => setIsPlaying(true)}
                  className="relative w-full h-full group"
                  aria-label="Play OpenRecruiting product demo video"
                >
                  <Image
                    id="product-showcase-thumbnail"
                    src={`https://i.ytimg.com/vi/${videoId}/maxresdefault.jpg`}
                    alt="OpenRecruiting Product Demo"
                    fill
                    sizes="(max-width: 768px) 100vw, 896px"
                    className="object-cover"
                  />
                  <div
                    id="product-showcase-overlay"
                    className="absolute inset-0 bg-black/20 group-hover:bg-black/30 transition-colors flex items-center justify-center"
                  >
                    <div
                      id="product-showcase-play-icon"
                      className="w-16 h-16 md:w-20 md:h-20 rounded-full bg-white/20 backdrop-blur-sm group-hover:bg-white/30 flex items-center justify-center transition-all group-hover:scale-110"
                    >
                      <Play className="w-7 h-7 md:w-9 md:h-9 text-white ml-1" />
                    </div>
                  </div>
                </button>
              )}
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

export { ProductShowcase };
