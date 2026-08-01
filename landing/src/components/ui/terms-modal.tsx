"use client";

import { X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface TermsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

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
        className="bg-white dark:bg-background rounded-2xl border border-border shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col relative"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-6 border-b border-border">
          <h2 id="terms-modal-title" className="text-xl font-bold">
            TERMS OF SERVICE
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
          className="flex-1 overflow-y-auto p-6 space-y-6 text-sm leading-relaxed"
        >
          <p className="text-muted-foreground">
            Website: http://localhost:3000
          </p>
          <p>
            These Terms of Service (&quot;Terms&quot;) govern your access to, and use of
            the website operated by OpenRecruiting.ai (&quot;Company&quot;, &quot;we&quot;, &quot;us&quot;, or
            &quot;our&quot;), including all related applications, software, tools, APIs,
            and services (collectively, the &quot;Services&quot;).
          </p>
          <p>
            By accessing or using the Services, you agree to be legally bound by
            these Terms. If you do not agree, you must not use the Services.
          </p>

          <section>
            <h3 className="font-semibold text-base mb-2">1. Eligibility</h3>
            <p className="mb-2">You must:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Be at least 18 years old;</li>
              <li>Have the legal capacity to enter into binding agreements;</li>
              <li>Use the Services in compliance with applicable laws.</li>
            </ul>
            <p className="mt-2">
              If you are using the Services on behalf of an organization, you
              represent that you have authority to bind that entity.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              2. Account Registration
            </h3>
            <p className="mb-2">
              To access certain features, you may be required to create an
              account. You agree to:
            </p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Provide accurate and complete information;</li>
              <li>Maintain confidentiality of login credentials;</li>
              <li>
                Accept responsibility for all activities under your account.
              </li>
            </ul>
            <p className="mt-2">
              We reserve the right to suspend or terminate accounts that violate
              these Terms.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              3. Description of Services
            </h3>
            <p>
              OpenRecruiting.ai provides AI-driven tools designed to assist with
              interview preparation, structured hiring workflows, candidate
              analysis, and related recruitment support functions.
            </p>
            <p className="mt-2">
              We may modify, suspend, or discontinue any part of the Services at
              any time without prior notice.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              4. User Responsibilities
            </h3>
            <p className="mb-2">You agree that you will not:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                Use the Services for unlawful, discriminatory, or fraudulent
                purposes;
              </li>
              <li>
                Upload or transmit content that violates intellectual property
                rights;
              </li>
              <li>
                Reverse engineer, copy, or exploit the platform without
                authorisation;
              </li>
              <li>
                Use automated systems (bots, scrapers) without permission;
              </li>
              <li>Input sensitive personal data unless legally permitted.</li>
            </ul>
            <p className="mt-2">
              You are solely responsible for content you upload or generate
              through the Services.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              5. AI-Generated Content Disclaimer
            </h3>
            <p className="mb-2">
              The Services may generate recommendations, summaries, evaluations,
              or other outputs using artificial intelligence.
            </p>
            <p className="mb-2">You acknowledge that:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>AI outputs may contain inaccuracies;</li>
              <li>
                Outputs should not be relied upon as legal, HR, or professional
                advice;
              </li>
              <li>Final hiring decisions remain your sole responsibility.</li>
            </ul>
            <p className="mt-2">
              The Company is not liable for decisions made based on AI-generated
              outputs.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              6. Intellectual Property
            </h3>
            <p className="mb-2">
              All rights, title, and interest in and to the Services, including:
            </p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Software</li>
              <li>Algorithms</li>
              <li>UI/UX</li>
              <li>Trademarks</li>
              <li>Content</li>
            </ul>
            <p className="mt-2">are owned by OpenRecruiting.ai or its licensors.</p>
            <p className="mt-2">
              You are granted a limited, non-exclusive, non-transferable license
              to use the Services strictly in accordance with these Terms. You
              may not reproduce, distribute, modify, or create derivative works
              without written consent.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">7. User Content</h3>
            <p className="mb-2">
              You retain ownership of the data and content you submit (&quot;User
              Content&quot;).
            </p>
            <p className="mb-2">
              By submitting User Content, you grant OpenRecruiting.ai a limited license
              to:
            </p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Host</li>
              <li>Process</li>
              <li>Analyse</li>
              <li>Display</li>
            </ul>
            <p className="mt-2">
              such content solely to provide and improve the Services.
            </p>
            <p className="mt-2">
              We do not claim ownership over your proprietary hiring data.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              8. Fees, Credits and Payments
            </h3>

            <h4 className="font-semibold mt-4 mb-2">
              8.1 Free Credits for New Users
            </h4>
            <p className="mb-2">
              Upon registration, new users may be granted a limited number of
              promotional or introductory credits (&quot;Free Credits&quot;) to access and
              evaluate certain features of the Services. Free Credits:
            </p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Are provided at the Company&apos;s sole discretion;</li>
              <li>May be subject to expiration or usage limits;</li>
              <li>Have no monetary value;</li>
              <li>Are non-transferable and non-refundable.</li>
            </ul>
            <p className="mt-2">
              The Company reserves the right to modify, withdraw, or discontinue
              Free Credits at any time without prior notice.
            </p>

            <h4 className="font-semibold mt-4 mb-2">
              8.2 Usage-Based Billing After Credit Expiry
            </h4>
            <p className="mb-2">
              Once Free Credits are exhausted or expired, continued access to
              paid features of the Services shall be subject to usage-based fees.
            </p>
            <p className="mb-2">
              By continuing to use the Services after depletion of Free Credits,
              you agree to:
            </p>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                Pay applicable fees based on your actual usage, as displayed on
                the platform or invoice;
              </li>
              <li>
                Maintain a valid payment method (including credit/debit card or
                other accepted payment method) on file;
              </li>
              <li>
                Authorize the Company to charge such payment method for all
                incurred fees.
              </li>
            </ul>
            <p className="mt-2">
              All invoices are payable within the timeline specified therein.
              Failure to make timely payment may result in suspension or
              restriction of access to the Services.
            </p>

            <h4 className="font-semibold mt-4 mb-2">8.3 Pricing Changes</h4>
            <p>
              The Company reserves the right to revise pricing, introduce new
              charges, or modify billing structures at any time on a prospective
              basis. Updated pricing shall become effective upon posting on the
              website or written notification via email or WhatsApp.
            </p>
            <p className="mt-2">
              Continued use of the Services after such changes constitutes
              acceptance of the revised pricing.
            </p>

            <h4 className="font-semibold mt-4 mb-2">8.4 Refunds</h4>
            <p>
              Unless expressly stated otherwise in a separate written agreement,
              all fees are non-refundable.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              9. Data Protection and Privacy
            </h3>
            <p className="mb-2">
              Your use of the Services is subject to our Privacy Policy.
            </p>
            <p className="mb-2">
              If you are processing candidate personal data, you agree to comply
              with applicable data protection laws, including (if applicable):
            </p>
            <ul className="list-disc pl-6 space-y-1">
              <li>The Digital Personal Data Protection Act, 2023</li>
              <li>
                The General Data Protection Regulation (if EU data subjects are
                involved)
              </li>
            </ul>
            <p className="mt-2">
              OpenRecruiting.ai acts as a data processor where applicable.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              10. Confidentiality
            </h3>
            <p>
              Each party agrees to maintain confidentiality of proprietary and
              confidential information disclosed by either Party.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">11. Disclaimers</h3>
            <p className="mb-2">
              The Services are provided &quot;AS IS&quot; and &quot;AS AVAILABLE&quot;.
            </p>
            <p className="mb-2">We disclaim all warranties, including:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Accuracy</li>
              <li>Reliability</li>
              <li>Fitness for a particular purpose</li>
              <li>Non-infringement</li>
            </ul>
            <p className="mt-2">
              We do not guarantee uninterrupted or error-free service.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              12. Limitation of Liability
            </h3>
            <p className="mb-2">To the maximum extent permitted by law:</p>
            <p className="mb-2">OpenRecruiting.ai shall not be liable for:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Indirect, incidental, or consequential damages;</li>
              <li>Loss of profits, business, or data;</li>
              <li>Decisions made based on AI outputs.</li>
            </ul>
            <p className="mt-2">
              Total liability shall not exceed the fees paid in the preceding 3
              months.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              13. Indemnification
            </h3>
            <p className="mb-2">
              You agree to indemnify and hold harmless OpenRecruiting.ai from any claims,
              damages, or liabilities arising from:
            </p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Your misuse of the Services;</li>
              <li>Violation of these Terms;</li>
              <li>Infringement of third-party rights.</li>
            </ul>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">14. Termination</h3>
            <p className="mb-2">We may suspend or terminate your access:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>For violation of these Terms;</li>
              <li>For non-payment;</li>
              <li>For legal compliance reasons.</li>
            </ul>
            <p className="mt-2">
              Upon termination, your right to use the Services ceases
              immediately.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              15. Governing Law and Dispute Resolution
            </h3>
            <p>
              These Terms shall be governed by the laws of India.
            </p>
            <p className="mt-2">
              Any disputes shall be subject to the exclusive jurisdiction of
              courts located in Bangalore, Karnataka.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              16. Changes to Terms
            </h3>
            <p>
              We may update these Terms from time to time. Continued use after
              changes constitutes acceptance.
            </p>
          </section>

          <section>
            <h3 className="font-semibold text-base mb-2">
              17. Contact Information
            </h3>
            <p>
              For questions regarding these Terms:
            </p>
            <p className="mt-1 font-medium">Email: founder@example.com</p>
          </section>
        </div>

        <div className="p-6 border-t border-border flex justify-end">
          <Button
            id="terms-modal-close-bottom-btn"
            variant="outline"
            onClick={onClose}
            className="rounded-full px-8"
          >
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}
