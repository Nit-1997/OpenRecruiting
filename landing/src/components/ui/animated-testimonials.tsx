"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import Image from "next/image";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

type Testimonial = {
  quote: string;
  name: string;
  designation: string;
  src: string;
  isCustomer?: boolean;
};

export const AnimatedTestimonials = ({
  testimonials,
  autoplay = false,
  className,
}: {
  testimonials: Testimonial[];
  autoplay?: boolean;
  className?: string;
}) => {
  const [active, setActive] = useState(0);

  const handleNext = () => {
    setActive((prev) => (prev + 1) % testimonials.length);
  };

  const handlePrev = () => {
    setActive((prev) => (prev - 1 + testimonials.length) % testimonials.length);
  };

  const isActive = (index: number) => {
    return index === active;
  };

  useEffect(() => {
    if (autoplay) {
      const interval = setInterval(handleNext, 5000);
      return () => clearInterval(interval);
    }
  }, [autoplay]);

  const rotations = [-4, 7, -3, 5, -6, 8, -2, 4, -7, 3];

  return (
    <div id="animated-testimonials" className={cn("w-full", className)}>
      <div id="animated-testimonials-layout" className="relative grid grid-cols-1 md:grid-cols-2 gap-10">
        <div id="animated-testimonials-images">
          <div id="animated-testimonials-image-stack" className="relative h-64 md:h-80 w-full">
            <AnimatePresence>
              {testimonials.map((testimonial, index) => (
                <motion.div
                  key={testimonial.src}
                  id={`animated-testimonial-image-${index}`}
                  initial={{
                    opacity: 0,
                    scale: 0.9,
                    z: -100,
                    rotate: rotations[index],
                  }}
                  animate={{
                    opacity: isActive(index) ? 1 : 0.7,
                    scale: isActive(index) ? 1 : 0.95,
                    z: isActive(index) ? 0 : -100,
                    rotate: isActive(index) ? 0 : rotations[index],
                    zIndex: isActive(index)
                      ? 999
                      : testimonials.length + 2 - index,
                    y: isActive(index) ? [0, -80, 0] : 0,
                  }}
                  exit={{
                    opacity: 0,
                    scale: 0.9,
                    z: 100,
                    rotate: rotations[index],
                  }}
                  transition={{
                    duration: 0.4,
                    ease: "easeInOut",
                  }}
                  className="absolute inset-0 origin-bottom"
                >
                  <Image
                    src={testimonial.src}
                    alt={testimonial.name}
                    width={500}
                    height={500}
                    draggable={false}
                    className="h-full w-full rounded-3xl object-cover object-center"
                  />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </div>
        <div id="animated-testimonials-text" className="flex justify-between flex-col py-4">
          <motion.div
            key={active}
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -20, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
          >
            <div id="animated-testimonials-name-row" className="flex items-center gap-2.5">
              <h3 id="animated-testimonials-name" className="text-2xl font-bold text-[var(--lp-text-primary)]">
                {testimonials[active].name}
              </h3>
              {testimonials[active].isCustomer && (
                <span id="animated-testimonials-customer-badge" className="px-2.5 py-0.5 text-xs font-medium rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                  Customer
                </span>
              )}
            </div>
            <p id="animated-testimonials-designation" className="text-sm text-[var(--lp-text-muted)]">
              {testimonials[active].designation}
            </p>
            <p
              key={`quote-${active}`}
              id="animated-testimonials-quote"
              className="text-base text-[var(--lp-text-secondary)] mt-6 leading-relaxed animate-testimonial-quote-in"
            >
              {testimonials[active].quote}
            </p>
          </motion.div>
          <div id="animated-testimonials-nav" className="flex gap-4 pt-8 md:pt-0">
            <button
              id="animated-testimonials-prev-btn"
              type="button"
              aria-label="Previous testimonial"
              onClick={handlePrev}
              className="h-7 w-7 rounded-full bg-[var(--lp-surface-accent)] border border-[var(--lp-border)] flex items-center justify-center group/button cursor-pointer"
            >
              <ArrowLeft className="h-4 w-4 text-[var(--lp-text-primary)] group-hover/button:rotate-12 transition-transform duration-300" />
            </button>
            <button
              id="animated-testimonials-next-btn"
              type="button"
              aria-label="Next testimonial"
              onClick={handleNext}
              className="h-7 w-7 rounded-full bg-[var(--lp-surface-accent)] border border-[var(--lp-border)] flex items-center justify-center group/button cursor-pointer"
            >
              <ArrowRight className="h-4 w-4 text-[var(--lp-text-primary)] group-hover/button:-rotate-12 transition-transform duration-300" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
