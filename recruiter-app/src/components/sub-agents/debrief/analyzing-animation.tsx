'use client';

import { motion, useReducedMotion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { cn, pickAvatarFg } from '@/lib/utils';

interface AnalyzingAvatar {
  initials: string;
  color: string;
}

interface DebriefAnalyzingProps {
  id: string;
  roleTitle: string;
  candidateNames: string[];
  candidateAvatars: AnalyzingAvatar[];
  onDone?: () => void;
}

const STEP_INTERVAL_MS = 420;

export function DebriefAnalyzing({
  id,
  roleTitle,
  candidateNames,
  candidateAvatars,
  onDone,
}: DebriefAnalyzingProps) {
  const [stepIdx, setStepIdx] = useState(0);
  const reduceMotion = useReducedMotion();

  // The final step + the title reference the REAL role being debriefed, not a
  // hardcoded "Staff PM" (which showed the wrong role for non-PM debriefs).
  const steps = [
    'Pulling interview transcripts from Zoom + Meet',
    'Reading 16 scorecards across 4 rounds',
    'Weighing signal by interviewer calibration',
    'Clustering strengths, concerns, and open questions',
    `Ranking against the ${roleTitle} rubric`,
  ];

  useEffect(() => {
    if (stepIdx >= steps.length) {
      const t = setTimeout(() => onDone?.(), 300);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setStepIdx((i) => i + 1), STEP_INTERVAL_MS);
    return () => clearTimeout(t);
  }, [stepIdx, onDone, steps.length]);

  // P7 motion-reduce: the steps list still advances so users still see
  // the semantic "analyzing" signal, but the pulsing avatars + rotating
  // ring degrade to a static hold.
  const avatarAnimate = reduceMotion
    ? { scale: 1, opacity: 1 }
    : { scale: [0.92, 1.05, 0.92], opacity: [0.6, 1, 0.6] };
  const ringAnimate = reduceMotion ? { rotate: 0 } : { rotate: [0, 360] };

  return (
    <div
      id={id}
      className="flex max-w-[720px] flex-col gap-6 pt-10"
      aria-live="polite"
      aria-busy="true"
    >
      <div id={`${id}-avatars`} className="flex items-center gap-3">
        {candidateAvatars.map((a, idx) => (
          <motion.div
            key={a.initials}
            id={`${id}-avatar-${idx}`}
            className="relative flex h-[80px] w-[80px] items-center justify-center rounded-full font-mono text-[22px] text-text-primary"
            style={{ background: a.color, color: pickAvatarFg(a.color) }}
            initial={{ scale: 0.92, opacity: 0.6 }}
            animate={avatarAnimate}
            transition={{
              duration: reduceMotion ? 0 : 2.1,
              ease: 'easeInOut',
              repeat: reduceMotion ? 0 : Number.POSITIVE_INFINITY,
              delay: idx * 0.2,
            }}
          >
            <span id={`${id}-avatar-${idx}-initials`} className="font-medium" aria-hidden>
              {a.initials}
            </span>
            <motion.span
              id={`${id}-avatar-${idx}-ring`}
              aria-hidden
              className="absolute inset-[-8px] rounded-full border border-cortex-300 border-dashed"
              animate={ringAnimate}
              transition={{
                duration: reduceMotion ? 0 : 8,
                ease: 'linear',
                repeat: reduceMotion ? 0 : Number.POSITIVE_INFINITY,
                delay: idx * 0.3,
              }}
            />
          </motion.div>
        ))}
      </div>

      <div id={`${id}-body`}>
        <div
          id={`${id}-eyebrow`}
          className="mb-2 font-mono text-[10.5px] text-cortex-600 uppercase tracking-[0.18em]"
        >
          OpenRecruiting is analyzing
        </div>
        <h3
          id={`${id}-title`}
          className="max-w-[640px] font-display text-[26px] text-text-primary leading-[1.35] tracking-[-0.005em]"
        >
          Comparing{' '}
          <em id={`${id}-title-names`} className="font-display italic">
            {candidateNames.join(' · ')}
          </em>{' '}
          across the {roleTitle} rubric.
        </h3>

        <div id={`${id}-steps`} className="mt-5 flex flex-col gap-2">
          {steps.map((step, i) => {
            const state: 'done' | 'live' | 'pending' =
              i < stepIdx ? 'done' : i === stepIdx ? 'live' : 'pending';
            return (
              <div
                key={step}
                id={`${id}-step-${i}`}
                className={cn(
                  'flex items-center gap-3 font-sans text-[13.5px] transition-opacity',
                  state === 'done'
                    ? 'text-text-secondary opacity-100'
                    : state === 'live'
                      ? 'text-text-primary opacity-100'
                      : 'text-text-muted opacity-60',
                )}
              >
                <span
                  id={`${id}-step-${i}-ic`}
                  aria-hidden
                  className={cn(
                    'flex h-[18px] w-[18px] items-center justify-center rounded-full border',
                    state === 'done'
                      ? 'border-text-primary bg-text-primary text-white'
                      : state === 'live'
                        ? 'border-cortex-500 bg-white'
                        : 'border-border bg-white',
                  )}
                >
                  {state === 'done' && (
                    <svg
                      aria-hidden
                      viewBox="0 0 16 16"
                      width="10"
                      height="10"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2.5}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <title>done</title>
                      <polyline points="3 8 7 12 13 4" />
                    </svg>
                  )}
                  {state === 'live' && (
                    <motion.span
                      id={`${id}-step-${i}-dot`}
                      aria-hidden
                      className="h-2 w-2 rounded-full bg-cortex-500"
                      animate={
                        reduceMotion
                          ? { scale: 1, opacity: 1 }
                          : { scale: [1, 1.6, 1], opacity: [1, 0.5, 1] }
                      }
                      transition={{
                        duration: reduceMotion ? 0 : 0.9,
                        ease: 'easeInOut',
                        repeat: reduceMotion ? 0 : Number.POSITIVE_INFINITY,
                      }}
                    />
                  )}
                </span>
                <span id={`${id}-step-${i}-text`}>{step}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
