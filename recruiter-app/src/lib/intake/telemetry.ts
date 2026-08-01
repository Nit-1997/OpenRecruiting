/**
 * PostHog event helpers for the v2 intake UX (lobby + session shell).
 * Spec: docs/superpowers/specs/2026-05-28-v2-intake-ux-overhaul-recruiter-app-design.md §10
 */

type EvName =
  | 'intake.lobby.opened'
  | 'intake.lobby.message_sent'
  | 'intake.lobby.form_opened'
  | 'intake.lobby.form_submitted'
  | 'intake.lobby.session_resumed_from_chat'
  | 'intake.lobby.session_resumed_from_list'
  | 'intake.session.opened'
  | 'intake.session.paused'
  | 'intake.session.resumed'
  | 'intake.session.modality_switched'
  | 'intake.session.submitted'
  | 'intake.session.published'
  | 'intake.theme.toggled';

export function trackIntake(event: EvName, props: Record<string, unknown> = {}): void {
  try {
    const ph = (
      globalThis as { posthog?: { capture: (e: string, p?: Record<string, unknown>) => void } }
    ).posthog;
    if (ph) ph.capture(event, props);
  } catch {
    // PostHog may not be initialized in test/SSR — fail silently.
  }
}
