"use client";

import { X } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

const REPO_URL = "https://github.com/Nit-1997/OpenRecruiting";

interface TermsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Shown from the sign-up checkbox. This used to inline 400+ lines of terms —
 * a second copy of /terms that drifted from it, and the copy users actually
 * agreed to. It now summarises and links, so /terms is the only source of truth
 * for the wording.
 */
export function TermsModal({ isOpen, onClose }: TermsModalProps) {
  if (!isOpen) return null;

  return (
    <div
      id="terms-modal-overlay"
      className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        id="terms-modal-content"
        className="bg-white dark:bg-background rounded-2xl border border-border shadow-2xl w-full max-w-2xl flex flex-col relative"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-6 border-b border-border">
          <h2 id="terms-modal-title" className="text-xl font-bold">
            Terms of Use
          </h2>
          <button
            id="terms-modal-close-btn"
            type="button"
            className="p-2 hover:bg-secondary rounded-lg transition-colors cursor-pointer"
            onClick={onClose}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div
          id="terms-modal-body"
          className="flex-1 p-6 space-y-4 text-sm leading-relaxed"
        >
          <p id="terms-modal-intro" className="text-muted-foreground">
            OpenRecruiting is a free, open-source project — not a company and
            not a paid product. In short:
          </p>

          <ul id="terms-modal-points" className="list-disc pl-5 space-y-2">
            <li>
              <strong>Nothing is charged.</strong> There are no fees,
              subscriptions, or payment methods anywhere in the project.
            </li>
            <li>
              <strong>No warranty, no uptime promise.</strong> Provided
              &quot;as is&quot;. A hosted demo may be reset or switched off at
              any time, so use synthetic data rather than real candidate
              records.
            </li>
            <li>
              <strong>AI output can be wrong.</strong> Plans, scorecards and
              feedback are model-generated. They are not professional advice,
              and hiring decisions stay yours.
            </li>
            <li>
              <strong>Your data stays yours.</strong> It is not sold, and not
              used to train models.
            </li>
            <li>
              <strong>The software is Apache 2.0.</strong> You may run, modify
              and redistribute it freely. Self-host and you become the operator
              — and the data controller for whatever it processes.
            </li>
          </ul>

          <p id="terms-modal-full-text" className="text-muted-foreground">
            This summary is for convenience. The{" "}
            <Link
              id="terms-modal-terms-link"
              href="/terms"
              target="_blank"
              className="underline hover:text-foreground"
            >
              full Terms of Use
            </Link>{" "}
            and the{" "}
            <Link
              id="terms-modal-privacy-link"
              href="/privacy"
              target="_blank"
              className="underline hover:text-foreground"
            >
              Privacy Policy
            </Link>{" "}
            are what actually apply, and both are versioned in{" "}
            <a
              id="terms-modal-repo-link"
              href={REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-foreground"
            >
              the repository
            </a>
            .
          </p>
        </div>

        <div className="p-6 border-t border-border flex justify-end">
          <Button id="terms-modal-done-btn" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}
