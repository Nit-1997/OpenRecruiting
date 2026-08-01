"""ATS sync-event processing: the webhook receiver persists events to
ats_webhook_events; the drainer applies them through handlers → adapters →
policy RPCs. Spec: docs/superpowers/specs/2026-06-11-knit-ats-phase2-*."""
