import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "OpenRecruiting Terms of Service — governing your use of our AI-powered interview intelligence platform.",
  alternates: { canonical: "http://localhost:3000/terms" },
};

export default function TermsPage() {
  return (
    <main id="terms-page" className="min-h-screen bg-[var(--lp-bg)]">
      <div id="terms-container" className="max-w-3xl mx-auto px-6 py-16">
        <Link href="/" id="terms-back-link" className="text-sm text-[var(--lp-text-muted)] hover:text-[var(--lp-text-primary)] transition-colors mb-8 inline-block">
          &larr; Back to localhost:3000
        </Link>

        <h1 id="terms-heading" className="text-3xl font-bold text-[var(--lp-text-primary)] mb-2">Terms of Service</h1>
        <p id="terms-effective-date" className="text-sm text-[var(--lp-text-muted)] mb-10">Effective Date: March 15, 2026</p>

        <div id="terms-body" className="space-y-8 text-sm leading-relaxed text-[var(--lp-text-secondary)]">
          <p>Website: http://localhost:3000</p>
          <p>
            These Terms of Service (&quot;Terms&quot;) govern your access to, and use of the website operated by OpenRecruiting.ai
            (&quot;Company&quot;, &quot;we&quot;, &quot;us&quot;, or &quot;our&quot;), including all related applications, software, tools, APIs,
            and services (collectively, the &quot;Services&quot;).
          </p>
          <p>By accessing or using the Services, you agree to be legally bound by these Terms. If you do not agree, you must not use the Services.</p>

          <section id="terms-section-1">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">1. Eligibility</h2>
            <p className="mb-2">You must:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Be at least 18 years old;</li>
              <li>Have the legal capacity to enter into binding agreements;</li>
              <li>Use the Services in compliance with applicable laws.</li>
            </ul>
            <p className="mt-2">If you are using the Services on behalf of an organization, you represent that you have authority to bind that entity.</p>
          </section>

          <section id="terms-section-2">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">2. Account Registration</h2>
            <p className="mb-2">To access certain features, you may be required to create an account. You agree to:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Provide accurate and complete information;</li>
              <li>Maintain confidentiality of login credentials;</li>
              <li>Accept responsibility for all activities under your account.</li>
            </ul>
            <p className="mt-2">We reserve the right to suspend or terminate accounts that violate these Terms.</p>
          </section>

          <section id="terms-section-3">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">3. Description of Services</h2>
            <p>OpenRecruiting.ai provides AI-driven tools designed to assist with interview preparation, structured hiring workflows, candidate analysis, and related recruitment support functions.</p>
            <p className="mt-2">We may modify, suspend, or discontinue any part of the Services at any time without prior notice.</p>
          </section>

          <section id="terms-section-4">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">4. User Responsibilities</h2>
            <p className="mb-2">You agree that you will not:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Use the Services for unlawful, discriminatory, or fraudulent purposes;</li>
              <li>Upload or transmit content that violates intellectual property rights;</li>
              <li>Reverse engineer, copy, or exploit the platform without authorisation;</li>
              <li>Use automated systems (bots, scrapers) without permission;</li>
              <li>Input sensitive personal data unless legally permitted.</li>
            </ul>
            <p className="mt-2">You are solely responsible for content you upload or generate through the Services.</p>
          </section>

          <section id="terms-section-5">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">5. AI-Generated Content Disclaimer</h2>
            <p className="mb-2">The Services may generate recommendations, summaries, evaluations, or other outputs using artificial intelligence.</p>
            <p className="mb-2">You acknowledge that:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>AI outputs may contain inaccuracies;</li>
              <li>Outputs should not be relied upon as legal, HR, or professional advice;</li>
              <li>Final hiring decisions remain your sole responsibility.</li>
            </ul>
            <p className="mt-2">The Company is not liable for decisions made based on AI-generated outputs.</p>
          </section>

          <section id="terms-section-6">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">6. Intellectual Property</h2>
            <p className="mb-2">All rights, title, and interest in and to the Services, including software, algorithms, UI/UX, trademarks, and content are owned by OpenRecruiting.ai or its licensors.</p>
            <p className="mt-2">You are granted a limited, non-exclusive, non-transferable license to use the Services strictly in accordance with these Terms. You may not reproduce, distribute, modify, or create derivative works without written consent.</p>
          </section>

          <section id="terms-section-7">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">7. User Content</h2>
            <p className="mb-2">You retain ownership of the data and content you submit (&quot;User Content&quot;).</p>
            <p className="mb-2">By submitting User Content, you grant OpenRecruiting.ai a limited license to host, process, analyse, and display such content solely to provide and improve the Services.</p>
            <p className="mt-2">We do not claim ownership over your proprietary hiring data.</p>
          </section>

          <section id="terms-section-8">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">8. Fees, Credits and Payments</h2>

            <h3 className="font-semibold mt-4 mb-2">8.1 Free Credits for New Users</h3>
            <p className="mb-2">Upon registration, new users may be granted a limited number of promotional or introductory credits (&quot;Free Credits&quot;) to access and evaluate certain features of the Services. Free Credits:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Are provided at the Company&apos;s sole discretion;</li>
              <li>May be subject to expiration or usage limits;</li>
              <li>Have no monetary value;</li>
              <li>Are non-transferable and non-refundable.</li>
            </ul>
            <p className="mt-2">The Company reserves the right to modify, withdraw, or discontinue Free Credits at any time without prior notice.</p>

            <h3 className="font-semibold mt-4 mb-2">8.2 Usage-Based Billing After Credit Expiry</h3>
            <p className="mb-2">Once Free Credits are exhausted or expired, continued access to paid features of the Services shall be subject to usage-based fees.</p>
            <p className="mb-2">By continuing to use the Services after depletion of Free Credits, you agree to:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Pay applicable fees based on your actual usage, as displayed on the platform or invoice;</li>
              <li>Maintain a valid payment method on file;</li>
              <li>Authorize the Company to charge such payment method for all incurred fees.</li>
            </ul>

            <h3 className="font-semibold mt-4 mb-2">8.3 Pricing Changes</h3>
            <p>The Company reserves the right to revise pricing, introduce new charges, or modify billing structures at any time on a prospective basis. Updated pricing shall become effective upon posting on the website or written notification.</p>

            <h3 className="font-semibold mt-4 mb-2">8.4 Refunds</h3>
            <p>Unless expressly stated otherwise in a separate written agreement, all fees are non-refundable.</p>
          </section>

          <section id="terms-section-9">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">9. Data Protection and Privacy</h2>
            <p className="mb-2">Your use of the Services is subject to our <Link href="/privacy" className="underline hover:text-[var(--lp-text-primary)]">Privacy Policy</Link>.</p>
            <p className="mb-2">If you are processing candidate personal data, you agree to comply with applicable data protection laws, including (if applicable):</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>The Digital Personal Data Protection Act, 2023</li>
              <li>The General Data Protection Regulation (if EU data subjects are involved)</li>
            </ul>
            <p className="mt-2">OpenRecruiting.ai acts as a data processor where applicable.</p>
          </section>

          <section id="terms-section-10">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">10. Confidentiality</h2>
            <p>Each party agrees to maintain confidentiality of proprietary and confidential information disclosed by either Party.</p>
          </section>

          <section id="terms-section-11">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">11. Disclaimers</h2>
            <p className="mb-2">The Services are provided &quot;AS IS&quot; and &quot;AS AVAILABLE&quot;.</p>
            <p className="mb-2">We disclaim all warranties, including accuracy, reliability, fitness for a particular purpose, and non-infringement.</p>
            <p>We do not guarantee uninterrupted or error-free service.</p>
          </section>

          <section id="terms-section-12">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">12. Limitation of Liability</h2>
            <p className="mb-2">To the maximum extent permitted by law, OpenRecruiting.ai shall not be liable for:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Indirect, incidental, or consequential damages;</li>
              <li>Loss of profits, business, or data;</li>
              <li>Decisions made based on AI outputs.</li>
            </ul>
            <p className="mt-2">Total liability shall not exceed the fees paid in the preceding 3 months.</p>
          </section>

          <section id="terms-section-13">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">13. Indemnification</h2>
            <p className="mb-2">You agree to indemnify and hold harmless OpenRecruiting.ai from any claims, damages, or liabilities arising from:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Your misuse of the Services;</li>
              <li>Violation of these Terms;</li>
              <li>Infringement of third-party rights.</li>
            </ul>
          </section>

          <section id="terms-section-14">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">14. Termination</h2>
            <p className="mb-2">We may suspend or terminate your access:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>For violation of these Terms;</li>
              <li>For non-payment;</li>
              <li>For legal compliance reasons.</li>
            </ul>
            <p className="mt-2">Upon termination, your right to use the Services ceases immediately.</p>
          </section>

          <section id="terms-section-15">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">15. Governing Law and Dispute Resolution</h2>
            <p>These Terms shall be governed by the laws of India.</p>
            <p className="mt-2">Any disputes shall be subject to the exclusive jurisdiction of courts located in Bangalore, Karnataka.</p>
          </section>

          <section id="terms-section-16">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">16. Changes to Terms</h2>
            <p>We may update these Terms from time to time. Continued use after changes constitutes acceptance.</p>
          </section>

          <section id="terms-section-17">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">17. Contact Information</h2>
            <p>For questions regarding these Terms:</p>
            <p className="mt-1 font-medium">Email: founder@example.com</p>
          </section>
        </div>
      </div>
    </main>
  );
}
