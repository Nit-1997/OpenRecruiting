"""
Recall.ai webhook handler package — v2.

v1 ships a single ~1700-line `webhooks/recall.py`. v2 splits the same
responsibilities into focused modules so each Recall event type has one
file (SRP), and shared concepts (status map, speaker name set,
interviewer detection heuristic) live in a single source (DRY).

Public surface:
    - signature.verify_webhook_signature(request)  → bool
    - bot_status_handler.handle_bot_status_change(...)
    - participant_handler.handle_participant_join / handle_participant_leave
    - transcript_handler.handle_transcript_data
    - chat_handler.handle_chat_message
    - recording_handler.fetch_and_store_recording  (BackgroundTask)
    - notifications.notify_bot_not_admitted        (BackgroundTask)
    - feedback_collection.trigger_feedback_collection

Routers in `app/api/v2/routers/webhooks.py` are intentionally thin —
they verify the signature, parse the envelope, then dispatch.
"""

# Submodules are imported lazily by the router / handlers as needed,
# not re-exported here, to avoid an import cycle through
# recording_handler → feedback_job_service → supabase.
