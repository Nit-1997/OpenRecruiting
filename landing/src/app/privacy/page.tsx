import type { Metadata } from "next";
import Link from "next/link";

const REPO_URL = "https://github.com/Nit-1997/OpenRecruiting";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description:
    "How the maintainer-hosted OpenRecruiting demo handles data. OpenRecruiting is free and open source — if you run your own instance, you are the data controller and this policy does not apply to you.",
  alternates: { canonical: "http://localhost:3000/privacy" },
};

export default function PrivacyPage() {
  return (
    <main id="privacy-page" className="min-h-screen bg-[var(--lp-bg)]">
      <div id="privacy-container" className="max-w-3xl mx-auto px-6 py-16">
        <Link
          href="/"
          id="privacy-back-link"
          className="text-sm text-[var(--lp-text-muted)] hover:text-[var(--lp-text-primary)] transition-colors mb-8 inline-block"
        >
          &larr; Back to home
        </Link>

        <h1
          id="privacy-heading"
          className="text-3xl font-bold text-[var(--lp-text-primary)] mb-2"
        >
          Privacy Policy
        </h1>
        <p
          id="privacy-effective-date"
          className="text-sm text-[var(--lp-text-muted)] mb-10"
        >
          Last updated: August 12, 2026
        </p>

        <div
          id="privacy-body"
          className="space-y-8 text-sm leading-relaxed text-[var(--lp-text-secondary)]"
        >
          <div
            id="privacy-summary"
            className="rounded-xl border border-[var(--lp-border)] p-5 space-y-2"
          >
            <p className="font-medium text-[var(--lp-text-primary)]">
              Who this applies to
            </p>
            <p>
              OpenRecruiting is a free, open-source project — not a company, and
              not a paid service. This policy describes a{" "}
              <strong>demo instance hosted by the maintainers</strong>.
            </p>
            <p>
              <strong>If you run your own instance, none of this applies to
              you.</strong> Your deployment talks to your own database and your
              own API keys. The maintainers cannot see it and receive nothing
              from it. You are the data controller, and writing your own privacy
              notice is your responsibility.
            </p>
            <p>
              Nothing here is sold, and there is no advertising, no data broker,
              and no payment processing anywhere in the project.
            </p>
          </div>

          <section id="privacy-section-1">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              1. What a hosted instance collects
            </h2>

            <h3 className="font-semibold mt-4 mb-2">1.1 What you provide</h3>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                <strong>Account data:</strong> name, email address, and
                organisation name at registration.
              </li>
              <li>
                <strong>Recruitment data:</strong> requisitions, candidate names
                and emails, interview plans, scorecards, and feedback you create
                or upload. Please use synthetic data on a demo instance.
              </li>
              <li>
                <strong>Conversation data:</strong> messages you send to the
                in-app agents.
              </li>
            </ul>

            <h3 className="font-semibold mt-4 mb-2">
              1.2 What is collected automatically
            </h3>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                <strong>Usage data:</strong> pages visited, features used,
                timestamps, and interaction patterns, via PostHog. This is tied
                to an identified user, not anonymous.
              </li>
              <li>
                <strong>Device data:</strong> browser, operating system, IP
                address, and device identifiers.
              </li>
              <li>
                <strong>Cookies:</strong> a session cookie for authentication,
                plus PostHog&apos;s analytics cookies. Details in section 6.
              </li>
            </ul>

            <h3 className="font-semibold mt-4 mb-2">
              1.3 What comes from integrations you enable
            </h3>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                <strong>Google sign-in:</strong> your email and basic profile,
                received through Supabase Auth if you choose that method.
              </li>
              <li>
                <strong>Meeting capture:</strong> audio and video from
                interviews a bot joins, via Recall.ai, used only to produce
                transcripts and feedback.
              </li>
              <li>
                <strong>ATS sync:</strong> jobs, candidates and applications
                from a system you connect yourself, via Knit.
              </li>
            </ul>
            <p className="mt-2">
              Meeting capture is the most sensitive of these. Recording people
              usually requires telling them, and often their consent — that
              obligation is on whoever runs the instance and schedules the bot.
            </p>
          </section>

          <section id="privacy-section-2">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              2. What it is used for
            </h2>
            <ul className="list-disc pl-6 space-y-1">
              <li>Operating the instance and your account;</li>
              <li>
                Generating interview plans, feedback, and scorecards, and
                running voice intake and debrief sessions;
              </li>
              <li>
                Sending transactional notifications, such as feedback being
                ready;
              </li>
              <li>Understanding which features are used, so they improve;</li>
              <li>Detecting and preventing abuse;</li>
              <li>Meeting legal obligations.</li>
            </ul>
            <p className="mt-2">
              There is no billing, so none of it is used for payments, pricing,
              or credit decisions. It is not used for advertising or profiling
              unrelated to the product.
            </p>
          </section>

          <section id="privacy-section-3">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              3. AI processing
            </h2>
            <p className="mb-2">
              Content is sent to third-party model providers — Anthropic and
              OpenAI — to generate plans, feedback, scorecards, and voice
              conversations. Deepgram is used for speech-to-text.
            </p>
            <p>
              Access is through paid API tiers, under which these providers do
              not train their models on the content sent to them. If you
              self-host, this is governed by your own agreements with whichever
              providers you configure, and you may point the gateway at a local
              model instead so nothing leaves your machine.
            </p>
          </section>

          <section id="privacy-section-4">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              4. Storage and security
            </h2>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                <strong>Database:</strong> Supabase (PostgreSQL), with Row Level
                Security enforcing separation between organisations.
              </li>
              <li>
                <strong>Knowledge graph:</strong> Neo4j, holding derived
                recruitment context.
              </li>
              <li>
                <strong>In transit:</strong> encrypted over TLS.
              </li>
              <li>
                <strong>Access control:</strong> service-to-service calls
                require a shared secret; database access is limited to service
                roles.
              </li>
              <li>
                <strong>Recordings:</strong> processed by Recall.ai; transcripts
                are stored for feedback generation, and raw recordings are not
                retained by the project.
              </li>
            </ul>
            <p className="mt-2">
              This is a volunteer-maintained project, not a certified provider.
              There is no SOC 2 report, no security team, and no guarantee — if
              you need assurances, self-host and apply your own controls.
            </p>
          </section>

          <section id="privacy-section-5">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              5. Who data is shared with
            </h2>
            <p className="mb-2">
              Nothing is sold, ever. On a hosted instance, data reaches only:
            </p>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                <strong>Infrastructure and processors:</strong> Supabase
                (database and auth), Anthropic and OpenAI (model inference),
                Deepgram (speech-to-text), Recall.ai (meeting capture), Knit
                (ATS sync, if connected), Cloudflare (network), PostHog
                (analytics).
              </li>
              <li>
                <strong>Your own organisation:</strong> teammates in your
                organisation can see its requisitions, candidates, and feedback.
              </li>
              <li>
                <strong>Legal requirement:</strong> where compelled by law.
              </li>
            </ul>
            <p className="mt-2">
              Which of these apply to a self-hosted instance is entirely your
              choice — every one is optional and disabled without a key.
            </p>
          </section>

          <section id="privacy-section-6">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              6. Cookies
            </h2>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                <strong>Session cookie</strong> (
                <code>openrecruiting-auth</code>): keeps you signed in and is
                shared between the marketing site and the app. Essential — the
                app cannot work without it.
              </li>
              <li>
                <strong>PostHog cookies:</strong> product analytics.
              </li>
            </ul>
            <p className="mt-2">
              No third-party advertising cookies are used, and there are no ad
              networks or retargeting pixels.
            </p>
          </section>

          <section id="privacy-section-7">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              7. Retention
            </h2>
            <ul className="list-disc pl-6 space-y-1">
              <li>
                <strong>Account data:</strong> kept until the account is
                deleted.
              </li>
              <li>
                <strong>Recruitment data:</strong> kept until you delete the
                requisition, candidate, or account.
              </li>
              <li>
                <strong>Transcripts:</strong> kept for feedback generation; raw
                recordings are not retained.
              </li>
              <li>
                <strong>Agent conversations:</strong> kept for continuity, and
                deleted with the associated requisition or account.
              </li>
              <li>
                <strong>Analytics:</strong> per PostHog&apos;s retention
                settings.
              </li>
            </ul>
            <p className="mt-2">
              A demo instance may be reset at any time, which deletes everything
              on it. Do not treat it as storage.
            </p>
          </section>

          <section id="privacy-section-8">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              8. Your rights
            </h2>
            <p className="mb-2">
              Depending on where you live, you may have the right to access,
              correct, delete, export, or object to the processing of your
              personal data, and to withdraw consent.
            </p>
            <p>
              For a hosted instance, raise a request through the repository
              (section 10). If a request concerns a{" "}
              <strong>self-hosted instance</strong> — including a candidate
              asking about their data — it must go to whoever operates that
              instance. The maintainers have no access to it and cannot act on
              your behalf.
            </p>
          </section>

          <section id="privacy-section-9">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              9. International transfers, and children
            </h2>
            <p className="mb-2">
              The processors above operate in several countries, so data handled
              by a hosted instance may be processed outside your own. Standard
              contractual protections offered by those providers apply.
            </p>
            <p>
              The project is not intended for children, and personal data is not
              knowingly collected from them. If some reaches a hosted instance,
              it will be deleted.
            </p>
          </section>

          <section id="privacy-section-10">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">
              10. Changes and contact
            </h2>
            <p className="mb-2">
              This policy may be updated; the version in effect is the one on
              this page, dated above, and its full history is in the repository.
            </p>
            <p>
              Privacy questions and requests go through the repository:
            </p>
            <p className="mt-2">
              <a
                id="privacy-github-link"
                href={REPO_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-[var(--lp-text-primary)] font-medium"
              >
                github.com/Nit-1997/OpenRecruiting
              </a>
            </p>
            <p className="mt-2">
              For anything you would rather not discuss in public, open an issue
              asking for a private channel.
            </p>
          </section>
        </div>
      </div>
    </main>
  );
}
