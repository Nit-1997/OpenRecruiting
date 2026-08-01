"use client";

import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

export const BOOK_DEMO_URL = "https://example.com/demo";

interface CalendlyModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function CalendlyModal({ isOpen, onClose }: CalendlyModalProps) {
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 md:p-8">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Glassy container with equal padding */}
      <div className="relative z-10 w-full max-w-5xl max-h-[92vh] rounded-3xl border border-white/20 bg-white/10 backdrop-blur-xl shadow-[0_8px_32px_rgba(0,0,0,0.3)] p-3 md:p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-display text-lg font-light text-white ml-1">Book a Demo</h2>
          <button
            type="button"
            onClick={onClose}
            className="w-9 h-9 rounded-full bg-white/20 hover:bg-white/30 flex items-center justify-center transition-colors cursor-pointer"
          >
            <X className="w-5 h-5 text-white" />
          </button>
        </div>
        <div className="bg-white rounded-2xl overflow-hidden" style={{ height: "calc(92vh - 120px)" }}>
          <iframe
            src={`${BOOK_DEMO_URL}?layout=month_view&view=month`}
            title="Book a Demo"
            className="w-full h-full border-0"
            allow="payment"
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}
