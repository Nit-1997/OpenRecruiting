import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "OpenRecruiting Privacy Policy — how we collect, use, and protect your data.",
  alternates: { canonical: "http://localhost:3000/privacy" },
};

export default function PrivacyPage() {
  return (
    <main id="privacy-page" className="min-h-screen bg-[var(--lp-bg)]">
      <div id="privacy-container" className="max-w-3xl mx-auto px-6 py-16">
        <Link href="/" id="privacy-back-link" className="text-sm text-[var(--lp-text-muted)] hover:text-[var(--lp-text-primary)] transition-colors mb-8 inline-block">
          &larr; Back to localhost:3000
        </Link>

        <h1 id="privacy-heading" className="text-3xl font-bold text-[var(--lp-text-primary)] mb-2">Privacy Policy</h1>
        <p id="privacy-effective-date" className="text-sm text-[var(--lp-text-muted)] mb-10">Effective Date: March 15, 2026</p>

        <div id="privacy-body" className="space-y-8 text-sm leading-relaxed text-[var(--lp-text-secondary)]">
          <p>
            OpenRecruiting.ai (&quot;Company&quot;, &quot;we&quot;, &quot;us&quot;, or &quot;our&quot;) is committed to protecting your privacy.
            This Privacy Policy explains how we collect, use, disclose, and safeguard your information when you use our website
            at http://localhost:3000 and our related applications, tools, and services (collectively, the &quot;Services&quot;).
          </p>
          <p>By using the Services, you consent to the data practices described in this policy.</p>

          <section id="privacy-section-1">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">1. Information We Collect</h2>

            <h3 className="font-semibold mt-4 mb-2">1.1 Information You Provide</h3>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Account Data:</strong> Name, email address, organization name when you register.</li>
              <li><strong>Recruitment Data:</strong> Job requisitions, candidate names, emails, interview plans, and feedback that you create or upload.</li>
              <li><strong>Communication Data:</strong> Messages you send through our Slack integration or other chat interfaces.</li>
              <li><strong>Payment Data:</strong> Billing information processed by our third-party payment provider (Dodo Payments). We do not store full payment card details.</li>
            </ul>

            <h3 className="font-semibold mt-4 mb-2">1.2 Information Collected Automatically</h3>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Usage Data:</strong> Pages visited, features used, timestamps, and interaction patterns via PostHog analytics.</li>
              <li><strong>Device Data:</strong> Browser type, operating system, IP address, and device identifiers.</li>
              <li><strong>Cookies:</strong> Authentication cookies (e.g., <code>openrecruiting-auth</code>) for session management across subdomains.</li>
            </ul>

            <h3 className="font-semibold mt-4 mb-2">1.3 Information from Third-Party Integrations</h3>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Google Calendar:</strong> Calendar availability and event details (with your explicit OAuth consent). Scopes: <code>calendar.readonly</code>, <code>calendar.events</code>.</li>
              <li><strong>Slack:</strong> Workspace identity, user ID, and messages sent to the OpenRecruiting bot (with your workspace admin&apos;s consent).</li>
              <li><strong>Google Authentication:</strong> Email and profile information when you sign in with Google (via Supabase Auth).</li>
              <li><strong>Meeting Recordings:</strong> Audio and video from interviews conducted through integrated meeting platforms (via Recall.ai), used solely for generating interview feedback.</li>
            </ul>
          </section>

          <section id="privacy-section-2">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">2. How We Use Your Information</h2>
            <p className="mb-2">We use collected information to:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Provide, operate, and maintain the Services;</li>
              <li>Create and manage your account;</li>
              <li>Generate AI-powered interview plans, feedback, and scorecards;</li>
              <li>Schedule interviews and manage calendar integrations;</li>
              <li>Process Slack messages and deliver agent responses;</li>
              <li>Process payments and manage billing;</li>
              <li>Send transactional notifications (e.g., feedback ready, intake processed);</li>
              <li>Improve and personalize the Services;</li>
              <li>Detect and prevent fraud or abuse;</li>
              <li>Comply with legal obligations.</li>
            </ul>
          </section>

          <section id="privacy-section-3">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">3. AI Processing</h2>
            <p className="mb-2">We use third-party AI providers (including Anthropic Claude and OpenAI) to:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Generate structured interview plans from intake call transcripts;</li>
              <li>Produce interview feedback and candidate scorecards;</li>
              <li>Power the conversational Slack agent for recruiting operations;</li>
              <li>Conduct voice-based intake calls.</li>
            </ul>
            <p className="mt-2">Data sent to AI providers is used solely for generating outputs and is not used to train their models. We use API-based access with data processing agreements in place.</p>
          </section>

          <section id="privacy-section-4">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">4. Data Storage and Security</h2>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Database:</strong> All user data is stored in Supabase (PostgreSQL) with Row Level Security (RLS) enforcing multi-tenant data isolation.</li>
              <li><strong>Encryption:</strong> OAuth tokens (Google Calendar, Slack) are encrypted at rest using Fernet symmetric encryption.</li>
              <li><strong>Transport:</strong> All data in transit is encrypted via TLS/HTTPS.</li>
              <li><strong>Access Control:</strong> Internal API endpoints use secret-based authentication. Database access is restricted to service roles.</li>
              <li><strong>Meeting Recordings:</strong> Processed by Recall.ai and AWS Lambda. Transcripts are stored temporarily for feedback generation and are not retained beyond processing.</li>
            </ul>
          </section>

          <section id="privacy-section-5">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">5. Data Sharing and Disclosure</h2>
            <p className="mb-2">We do not sell your personal data. We share data only with:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Service Providers:</strong> Supabase (database), Anthropic/OpenAI (AI processing), Recall.ai (meeting recording), AWS (compute and Lambda functions), Dodo Payments (billing), PostHog (analytics).</li>
              <li><strong>Within Your Organization:</strong> Team members in your OpenRecruiting organization can access shared requisitions, candidates, and feedback.</li>
              <li><strong>Legal Requirements:</strong> When required by law, regulation, legal process, or government request.</li>
            </ul>
          </section>

          <section id="privacy-section-6">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">6. Your Rights</h2>
            <p className="mb-2">Depending on your jurisdiction, you may have the right to:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li>Access the personal data we hold about you;</li>
              <li>Request correction of inaccurate data;</li>
              <li>Request deletion of your data;</li>
              <li>Withdraw consent for optional data processing;</li>
              <li>Export your data in a portable format;</li>
              <li>Object to or restrict certain processing activities.</li>
            </ul>
            <p className="mt-2">To exercise these rights, contact us at <strong>founder@example.com</strong>.</p>
          </section>

          <section id="privacy-section-7">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">7. Cookies and Tracking</h2>
            <p className="mb-2">We use the following cookies:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>openrecruiting-auth:</strong> Authentication session cookie on the <code>.localhost:3000</code> domain (essential, cross-subdomain).</li>
              <li><strong>PostHog cookies:</strong> Analytics and product usage tracking (with <code>cross_subdomain_cookie: true</code>).</li>
            </ul>
            <p className="mt-2">We do not use third-party advertising cookies.</p>
          </section>

          <section id="privacy-section-8">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">8. Data Retention</h2>
            <p className="mb-2">We retain your data for as long as your account is active or as needed to provide the Services. Specifically:</p>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Account Data:</strong> Retained until account deletion.</li>
              <li><strong>Recruitment Data:</strong> Retained until you delete requisitions, candidates, or your account.</li>
              <li><strong>Meeting Transcripts:</strong> Retained for feedback generation; raw recordings are not stored permanently.</li>
              <li><strong>Chat History:</strong> Slack agent conversation history is retained for context continuity and can be cleared by the user at any time.</li>
              <li><strong>Analytics Data:</strong> Retained per PostHog&apos;s data retention policies.</li>
            </ul>
            <p className="mt-2">Upon account deletion, we will delete or anonymize your personal data within 30 days, except where retention is required by law.</p>
          </section>

          <section id="privacy-section-9">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">9. International Data Transfers</h2>
            <p>Your data may be processed in the United States (AWS, Supabase, AI providers) and India (our operations). We ensure appropriate safeguards are in place for cross-border transfers, including data processing agreements with our service providers.</p>
          </section>

          <section id="privacy-section-10">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">10. Children&apos;s Privacy</h2>
            <p>The Services are not intended for individuals under 18 years of age. We do not knowingly collect personal data from children. If we become aware of such collection, we will delete the data promptly.</p>
          </section>

          <section id="privacy-section-11">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">11. Changes to This Policy</h2>
            <p>We may update this Privacy Policy from time to time. We will notify you of material changes by posting the updated policy on this page with a revised effective date. Continued use of the Services after changes constitutes acceptance.</p>
          </section>

          <section id="privacy-section-12">
            <h2 className="text-lg font-semibold text-[var(--lp-text-primary)] mb-3">12. Contact Us</h2>
            <p>For questions or concerns about this Privacy Policy or our data practices:</p>
            <p className="mt-2"><strong>OpenRecruiting.ai</strong></p>
            <p>Email: <strong>founder@example.com</strong></p>
            <p>Website: <strong>http://localhost:3000</strong></p>
          </section>
        </div>
      </div>
    </main>
  );
}
