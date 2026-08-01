"""
v2 API surface — assembled router under `/api/v2`.

Architecture is layered:
  routers/   thin FastAPI routes; wire Depends, call services, return data
  services/  business logic; call Supabase / RPCs / external services
  schemas/   Pydantic DTOs
  core/      cross-cutting (exceptions, error handlers, deps, RPC plumbing)

Spec: docs/superpowers/specs/2026-05-18-roles-detail-v2-api-design.md
"""

from fastapi import APIRouter

from app.api.v2.routers import (
    admin,
    assistant,
    auth,
    billing,
    debrief,
    debrief_chat,
    feedback,
    intake_feature_flag,
    intake_heartbeat,
    intake_jd,
    intake_manual_edit,
    intake_parse_intent,
    intake_reprocess,
    intake_screening,
    intake_sessions,
    intake_submit,
    intake_switch,
    intake_text_messages,
    integrations_ats,
    integrations_gcal,
    integrations_slack,
    internal_calendar_intelligence,
    internal_cortex_token,
    internal_feedback,
    internal_screening,
    internal_slack_agent,
    internal_slack_integrations,
    journey,
    mcp_oauth,
    packet,
    personas,
    pipeline,
    plan,
    public_blog,
    public_feedback,
    public_screening,
    public_voice,
    recordings,
    roles,
    screening,
    screening_suggestion,
    team,
    untracked,
    voice,
    webhooks,
    webhooks_feedback,
    webhooks_knit,
    webhooks_slack,
)


v2_router = APIRouter(prefix="/api/v2")
v2_router.include_router(admin.router)
v2_router.include_router(auth.router)
v2_router.include_router(assistant.router)
v2_router.include_router(billing.router)
v2_router.include_router(debrief.router)
v2_router.include_router(debrief_chat.router)
v2_router.include_router(integrations_ats.router)
v2_router.include_router(integrations_gcal.router)
v2_router.include_router(integrations_slack.router)
v2_router.include_router(internal_cortex_token.router)
v2_router.include_router(mcp_oauth.router)
v2_router.include_router(roles.router)
v2_router.include_router(plan.router)
v2_router.include_router(screening.router)
v2_router.include_router(screening.cr_router)
v2_router.include_router(screening_suggestion.router)
v2_router.include_router(personas.router)
v2_router.include_router(pipeline.router)
v2_router.include_router(packet.router)
v2_router.include_router(journey.router)
v2_router.include_router(feedback.router)
v2_router.include_router(public_blog.router)
v2_router.include_router(public_feedback.router)
v2_router.include_router(public_screening.router)
v2_router.include_router(public_voice.router)
v2_router.include_router(internal_feedback.router)
v2_router.include_router(internal_screening.router)
v2_router.include_router(webhooks_feedback.router)
v2_router.include_router(intake_sessions.router)
v2_router.include_router(intake_manual_edit.router)
v2_router.include_router(intake_reprocess.router)
v2_router.include_router(intake_submit.router)
v2_router.include_router(intake_screening.router)
v2_router.include_router(intake_switch.router)
v2_router.include_router(intake_text_messages.router)
v2_router.include_router(intake_feature_flag.router)
v2_router.include_router(intake_parse_intent.router)
v2_router.include_router(intake_jd.router)
v2_router.include_router(intake_heartbeat.router)
v2_router.include_router(voice.router)
v2_router.include_router(recordings.router)
v2_router.include_router(team.router)
v2_router.include_router(untracked.router)
v2_router.include_router(webhooks.router)
v2_router.include_router(internal_calendar_intelligence.router)
v2_router.include_router(internal_slack_agent.router)
v2_router.include_router(internal_slack_integrations.router)
v2_router.include_router(webhooks_knit.router)
v2_router.include_router(webhooks_slack.router)


__all__ = ["v2_router"]
