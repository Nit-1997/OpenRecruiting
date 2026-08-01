"use client";

import * as React from "react";
import { useState, useRef } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ButtonProps } from "@/components/ui/button";

interface ParticleButtonProps extends ButtonProps {
  successDuration?: number;
  particleClassName?: string;
}

const PARTICLE_OFFSETS = [
  { x: 35, y: -45 },
  { x: -40, y: -30 },
  { x: 50, y: -55 },
  { x: -30, y: -50 },
  { x: 25, y: -35 },
  { x: -45, y: -40 },
];

function SuccessParticles({
  buttonRef,
  particleClassName,
}: {
  buttonRef: React.RefObject<HTMLButtonElement | null>;
  particleClassName: string;
}) {
  const rect = buttonRef.current?.getBoundingClientRect();
  if (!rect) return null;

  const centerX = rect.left + rect.width / 2;
  const centerY = rect.top + rect.height / 2;

  return (
    <>
      {PARTICLE_OFFSETS.map((offset, i) => (
        <div
          key={i}
          id={`particle-${i}`}
          className={cn("fixed w-1.5 h-1.5 rounded-full pointer-events-none z-50", particleClassName)}
          style={{
            left: centerX,
            top: centerY,
            "--particle-x": `${(i % 2 ? 1 : -1) * offset.x}px`,
            "--particle-y": `${offset.y}px`,
            animationDelay: `${i * 0.08}s`,
          } as React.CSSProperties}
        />
      ))}
    </>
  );
}

const ParticleButton = React.forwardRef<HTMLButtonElement, ParticleButtonProps>(
  (
    {
      children,
      onClick,
      successDuration = 800,
      particleClassName = "bg-[#111111]",
      className,
      ...props
    },
    ref,
  ) => {
    const [showParticles, setShowParticles] = useState(false);
    const internalRef = useRef<HTMLButtonElement>(null);
    const buttonRef = (ref as React.RefObject<HTMLButtonElement>) || internalRef;

    const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
      setShowParticles(true);
      setTimeout(() => setShowParticles(false), successDuration);
      onClick?.(e);
    };

    return (
      <>
        {showParticles && (
          <SuccessParticles
            buttonRef={buttonRef}
            particleClassName={particleClassName}
          />
        )}
        <Button
          ref={buttonRef}
          onClick={handleClick}
          className={cn(
            "relative transition-transform duration-100",
            showParticles && "scale-[0.97]",
            className,
          )}
          {...props}
        >
          {children}
        </Button>
      </>
    );
  },
);
ParticleButton.displayName = "ParticleButton";

export { ParticleButton };
export type { ParticleButtonProps };
