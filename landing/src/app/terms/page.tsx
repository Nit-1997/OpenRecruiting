import type { Metadata } from "next";
import Link from "next/link";

const REPO_URL = "https://github.com/Nit-1997/OpenRecruiting";

export const metadata: Metadata = {
  title: "Terms of Use",
  description:
    "Terms of Use for the OpenRecruiting demo instance. OpenRecruiting is a free, open-source project licensed under Apache 2.0 — the software itself is governed by its LICENSE, not by these terms.",
  alternates: { canonical: "http://localhost:3000/terms" },
};

export default function TermsPage() {
  return (
    <main id="terms-page" className="min-h-screen bg-[var(--lp-bg)]">
      <div id="terms-container" className="max-w-3xl mx-auto px-6 py-16">
        <Link
          href="/"
          id="terms-back-link"
          className="text-sm text-[var(--lp-text-muted)] hover:text-[var(--lp-text-primary)] transition-colors mb-8 inline-block"
        >
          &larr; Back to home
        </Link>

        <h1
          id="terms-heading"
          className="text-3xl font-bold text-[var(--lp-text-primary)] mb-2"
        >
          Terms of Use
        </h1>
        <p
          id="terms-effective-date"
          className="text-sm text-[var(--lp-text-muted)] mb-10"
        >
          Last updated: August 12, 2026
        </p>

        <div
          id="terms-body"
          className="space-y-8 text-sm leading-relaxed text-[var(--lp-text-secondary)]"
        >
          <div
            id="terms-summary"
            className="rounded-xl border border-[var(--lp-border)] p-5 space-y-2"
          >
            <p className="font-medium text-[var(--lp-text-primary)]">
              The short version
            </p>
            <p>
              OpenRecruiting is a free and open-source project. It is not a
              company, it is not sold, and nobody is billed for it. If you want
              to <em>use the software</em>, the{" "}
              <a
                id="terms-license-link"
                href={`${REPO_URL}/blob/main/LICENSE`}
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-[var(--lp-text-primary)]"
              >
                Apache License 2.0
              </a>{" "}
              is what governs you, and these terms are irrelevant. These terms
              apply only if you use a demo instance the maintainers happen to be
              hosting.
            </p>
          </div>

          <section id="terms-section-1">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              1. What these terms cover
            </h2>
            <p className="mb-2">
              OpenRecruiting is distributed as source code under the Apache
              License 2.0. Two different things can be meant by &quot;using
              OpenRecruiting&quot;, and they are governed differently:
            </p>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                <strong>Running your own instance.</strong> Governed entirely by
                the LICENSE in the repository. You do not need permission, an
                account, or an agreement with anyone. These terms do not apply.
              </li>
              <li>
                <strong>Using an instance hosted by the maintainers</strong> for
                demonstration purposes. These terms apply to that, and only
                that.
              </li>
            </ul>
            <p className="mt-2">
              &quot;The maintainers&quot; means the individual contributors to
              the project. There is no company, no employees, and no commercial
              entity behind it.
            </p>
          </section>

          <section id="terms-section-2">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              2. No fees, and no service commitment
            </h2>
            <p className="mb-2">
              There are no fees, subscriptions, credits for sale, or payment
              methods of any kind. Nothing on any page constitutes an offer to
              sell, and no support, uptime, or availability is promised.
            </p>
            <p>
              Any hosted instance is provided as a convenience and may be
              changed, reset, or switched off at any time without notice. Treat
              it as a demo, not a place to keep data you need. If you want
              continuity, run your own instance — that is the point of the
              project being open source.
            </p>
          </section>

          <section id="terms-section-3">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              3. If you self-host, the responsibility is yours
            </h2>
            <p className="mb-2">
              When you deploy your own instance you become the operator of that
              system. The maintainers have no access to it and no visibility
              into it. You are responsible for:
            </p>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                Being the data controller for any personal data your instance
                processes, including candidate data;
              </li>
              <li>
                Your own legal basis, notices, retention and deletion
                obligations under applicable data protection law;
              </li>
              <li>
                The API keys you configure and any costs the underlying
                providers charge you directly;
              </li>
              <li>
                Securing the deployment, and complying with employment and
                anti-discrimination law wherever you hire.
              </li>
            </ul>
          </section>

          <section id="terms-section-4">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              4. Accounts on a hosted instance
            </h2>
            <p className="mb-2">
              Where a hosted instance requires an account, you agree to provide
              accurate information, keep your credentials confidential, and
              accept responsibility for activity under your account. Access may
              be suspended or removed at any time, including for abuse or for no
              reason at all — see section 2.
            </p>
            <p>
              You must be old enough to form a binding agreement in your
              jurisdiction, and if you act for an organisation, you must be
              authorised to do so.
            </p>
          </section>

          <section id="terms-section-5">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              5. Acceptable use of a hosted instance
            </h2>
            <p className="mb-2">You agree not to:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                Use it for unlawful, discriminatory, or deceptive purposes;
              </li>
              <li>
                Upload real candidate data to a demo instance — use synthetic
                data, since a demo offers no retention or confidentiality
                guarantees;
              </li>
              <li>
                Upload content you have no right to share, or content that
                infringes someone else&apos;s rights;
              </li>
              <li>
                Attempt to disrupt it, exhaust its resources, or gain access to
                data that is not yours.
              </li>
            </ul>
            <p className="mt-2">
              Note that reverse engineering and modification are{" "}
              <strong>expressly permitted</strong> — the source is published and
              the LICENSE grants those rights. Only abuse of a shared hosted
              instance is restricted here.
            </p>
          </section>

          <section id="terms-section-6">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              6. AI-generated output
            </h2>
            <p className="mb-2">
              The software produces interview plans, summaries, scorecards and
              feedback using large language models. You acknowledge that:
            </p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Output can be wrong, incomplete, or misleading;</li>
              <li>
                It is not legal, HR, or professional advice, and must not be
                treated as such;
              </li>
              <li>
                Hiring decisions remain entirely yours, and you are responsible
                for reviewing output before acting on it;
              </li>
              <li>
                Automated assessment of candidates may be regulated where you
                operate, and meeting the requirements is your obligation.
              </li>
            </ul>
          </section>

          <section id="terms-section-7">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              7. Your content
            </h2>
            <p className="mb-2">
              You keep ownership of everything you submit. Nobody claims rights
              over your hiring data.
            </p>
            <p>
              On a hosted instance, the only permission granted is what is
              needed to run the thing in front of you: storing and processing
              your content so the features work. Your content is not used to
              train models, and is not sold or shared for advertising. See the{" "}
              <Link
                href="/privacy"
                className="underline hover:text-[var(--lp-text-primary)]"
              >
                Privacy Policy
              </Link>{" "}
              for specifics.
            </p>
          </section>

          <section id="terms-section-8">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              8. Licence and intellectual property
            </h2>
            <p className="mb-2">
              The source code is licensed under the{" "}
              <a
                id="terms-license-link-2"
                href={`${REPO_URL}/blob/main/LICENSE`}
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-[var(--lp-text-primary)]"
              >
                Apache License 2.0
              </a>
              . Under it you may use, copy, modify, distribute and sublicense
              the software, including commercially, subject to that
              licence&apos;s conditions — chiefly retaining notices and stating
              your changes. Contributions are accepted on the same terms.
            </p>
            <p>
              Nothing in this document narrows the rights that licence grants
              you. If these terms and the LICENSE ever appear to conflict over
              the software itself, the LICENSE governs. Project names and logos
              are not covered by the patent or trademark grant; please do not
              imply endorsement by the project for your fork or deployment.
            </p>
          </section>

          <section id="terms-section-9">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              9. No warranty
            </h2>
            <p>
              Consistent with section 7 of the Apache License 2.0, the software
              and any hosted instance are provided on an{" "}
              <strong>&quot;AS IS&quot; basis, without warranties or
              conditions of any kind</strong>, express or implied, including
              merchantability, fitness for a particular purpose, accuracy, or
              non-infringement. Nothing is guaranteed to be uninterrupted or
              error-free.
            </p>
          </section>

          <section id="terms-section-10">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              10. Limitation of liability
            </h2>
            <p className="mb-2">
              Consistent with section 8 of the Apache License 2.0, and to the
              maximum extent permitted by applicable law, no contributor is
              liable for any damages arising from the software or a hosted
              instance — including indirect, incidental, special, or
              consequential damages, lost profits, lost data, or decisions made
              on the basis of AI output.
            </p>
            <p>
              Because the project is provided free of charge, there are no fees
              against which to measure liability. Some jurisdictions do not
              allow certain exclusions, so parts of this may not apply to you.
            </p>
          </section>

          <section id="terms-section-11">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              11. Governing law
            </h2>
            <p>
              These terms are governed by the laws of India, without regard to
              conflict-of-law rules, and disputes about a maintainer-hosted
              instance are subject to the courts of Bangalore, Karnataka. This
              clause concerns these terms only; your rights under the Apache
              License 2.0 stand on their own.
            </p>
          </section>

          <section id="terms-section-12">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              12. Changes
            </h2>
            <p>
              These terms may be updated. The version in effect is whatever is
              published on this page, with the date shown above, and its history
              is visible in the repository. Continued use of a hosted instance
              after a change means you accept it.
            </p>
          </section>

          <section id="terms-section-13">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              13. Contact
            </h2>
            <p>
              Questions, corrections, and anything else about the project go
              through the repository — that way answers are public and useful to
              everyone:
            </p>
            <p className="mt-2">
              <a
                id="terms-github-link"
                href={REPO_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-[var(--lp-text-primary)] font-medium"
              >
                github.com/Nit-1997/OpenRecruiting
              </a>
            </p>
          </section>
        </div>
      </div>
    </main>
  );
}
