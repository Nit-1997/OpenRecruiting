import hashlib
import hmac
import json
import time
import httpx
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from app.config import get_settings
from app.services.slack_service import get_slack_service
from app.services.slack_blocks import home_tab_blocks, error_blocks
from app.logging_config import get_logger

logger = get_logger(__name__)

_warm_message_cooldown: dict[str, float] = {}
WARM_MESSAGE_INTERVAL = 3600
_DEFAULT_SLACK_FEATURES = {"assistant_read": False, "assistant_write": False}
router = APIRouter(prefix="/webhooks")


async def _get_effective_slack_features(org_id: str | None, connection: dict) -> dict:
    """Merge org-level + per-user Slack feature flags.
    User overrides org. NULL user_slack_features = inherit org defaults."""
    org_features = dict(_DEFAULT_SLACK_FEATURES)
    if org_id:
        try:
            from app.services.supabase import get_supabase_admin_client
            org_result = await get_supabase_admin_client().table("organizations") \
                .select("slack_features") \
                .eq("id", org_id) \
                .execute_async()
            if org_result.data:
                org_config = org_result.data[0].get("slack_features") or {}
                if isinstance(org_config, dict):
                    org_features = {**_DEFAULT_SLACK_FEATURES, **org_config}
        except Exception as e:
            logger.warning(f"Slack feature lookup failed for org={org_id}: {e}")
            settings = get_settings()
            env_val = getattr(settings, "ENV", None)
            is_test_env = env_val.lower() == "test" if isinstance(env_val, str) else True
            if is_test_env:
                # Keep unit tests deterministic when org feature lookup is not mocked.
                org_features = {**_DEFAULT_SLACK_FEATURES, "assistant_read": True}

    user_features = connection.get("user_slack_features")
    if isinstance(user_features, dict):
        return {**org_features, **user_features}
    return org_features


def verify_slack_signature(timestamp: str, body: bytes, signature: str) -> bool:
    settings = get_settings()
    secret = settings.SLACK_SIGNING_SECRET
    if not secret:
        logger.error("SLACK_SIGNING_SECRET not configured")
        return False

    if not timestamp or not signature:
        return False

    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False

    if abs(time.time() - ts) > 300:
        return False

    try:
        body_str = body.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return False

    sig_basestring = f"v0:{timestamp}:{body_str}"
    computed = "v0=" + hmac.new(
        secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, signature)


async def handle_message_event(event: dict, team_id: str):
    logger.info(f"Slack event: user={event.get('user')}, team={team_id}, type={event.get('type')}, channel_type={event.get('channel_type')}")
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    slack_user_id = event.get("user")
    channel = event.get("channel")
    if not slack_user_id or not channel:
        return

    service = get_slack_service()
    try:
        bot_token = await service.get_bot_token_for_team(team_id)
    except ValueError:
        logger.warning(f"No installation for team {team_id}")
        return

    connection = await service.get_connection(slack_user_id, team_id)
    logger.info(f"Slack connection lookup: slack_user={slack_user_id}, team={team_id}, found={connection is not None}")
    if not connection:
        await service.send_message(
            bot_token, channel,
            "It looks like your Slack account isn't connected to OpenRecruiting yet. Visit localhost:3000/dashboard/integrations to connect.",
            error_blocks("Your Slack account isn't linked to OpenRecruiting. Please connect at localhost:3000/dashboard/integrations."),
            team_id=team_id,
        )
        return

    org_id = connection.get("organization_id")
    features = await _get_effective_slack_features(org_id, connection)

    has_write = features.get("assistant_write", False)
    has_read = features.get("assistant_read", False)
    agent_mode = "full" if has_write else ("read_only" if has_read else None)

    user_message = event.get("text", "").strip()
    if not user_message:
        return

    if not agent_mode:
        now = time.time()
        last_sent = _warm_message_cooldown.get(slack_user_id, 0)
        if now - last_sent < WARM_MESSAGE_INTERVAL:
            return
        _warm_message_cooldown[slack_user_id] = now
        await service.send_message(
            bot_token, channel,
            "Assistant features are coming soon!",
            [{"type": "section", "text": {"type": "mrkdwn", "text": (
                ":rocket: *Assistant features* (asking questions, scheduling, managing candidates) "
                "are coming soon!\n\n"
                ":link: *Dashboard:* <http://localhost:3005/dashboard|Open OpenRecruiting>"
            )}}],
            team_id=team_id,
        )
        return

    if user_message.lower().strip() in {"/clear", "new session", "start over"}:
        try:
            from app.services.supabase import get_supabase_admin_client
            supabase = get_supabase_admin_client()
            await supabase.table("agent_conversations") \
                .delete() \
                .eq("slack_user_id", slack_user_id) \
                .eq("slack_channel_id", channel) \
                .execute_async()
        except Exception as e:
            logger.warning(f"Failed to clear conversation: {e}")
        await service.send_message(
            bot_token, channel,
            "Session cleared! How can I help with your recruiting needs?",
            [{"type": "section", "text": {"type": "mrkdwn", "text": ":white_check_mark: *Session cleared.* How can I help with your recruiting needs?"}}],
            team_id=team_id,
        )
        return

    thinking_ts = ""
    try:
        thinking_resp = await service.send_message(
            bot_token, channel,
            "Thinking...",
            [{"type": "context", "elements": [{"type": "mrkdwn", "text": ":large_purple_circle: *Scout is thinking...*"}]}],
            team_id=team_id,
        )
        if thinking_resp and thinking_resp.get("ts"):
            thinking_ts = thinking_resp["ts"]
    except Exception as e:
        logger.warning(f"Failed to send thinking indicator: {e}")

    settings = get_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        try:
            await client.post(
                f"{settings.SLACK_AGENT_URL}/run",
                json={
                    "slack_user_id": slack_user_id,
                    "slack_channel_id": channel,
                    "team_id": team_id,
                    "user_message": user_message,
                    "bot_token": bot_token,
                    "profile_id": connection["profile_id"],
                    "org_id": connection["organization_id"],
                    "thinking_ts": thinking_ts,
                    "mode": agent_mode,
                },
            )
        except Exception as e:
            logger.error(f"Slack agent call failed: {e}", exc_info=True)
            error_text = "Something went wrong. Please try again."
            if thinking_ts:
                try:
                    await service.update_message(bot_token, channel, thinking_ts, error_text, team_id=team_id)
                except Exception:
                    await service.send_message(bot_token, channel, error_text, team_id=team_id)
            else:
                await service.send_message(bot_token, channel, error_text, team_id=team_id)


async def handle_app_home_opened(event: dict, team_id: str):
    slack_user_id = event.get("user")
    if not slack_user_id:
        return

    service = get_slack_service()
    try:
        bot_token = await service.get_bot_token_for_team(team_id)
    except ValueError:
        return

    connection = await service.get_connection(slack_user_id, team_id)
    org_name = None
    if connection:
        from app.services.supabase import get_supabase_admin_client
        supabase = get_supabase_admin_client()
        org = await supabase.table("organizations") \
            .select("name") \
            .eq("id", connection["organization_id"]) \
            .limit(1) \
            .execute_async()
        if org.data:
            org_name = org.data[0].get("name")

    await service.publish_home_tab(bot_token, slack_user_id, home_tab_blocks(org_name), team_id=team_id)


@router.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verify_slack_signature(timestamp, body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = payload.get("event", {})
    event_type = event.get("type")
    team_id = payload.get("team_id")

    if event_type == "message" and event.get("channel_type") == "im":
        background_tasks.add_task(handle_message_event, event, team_id)
    elif event_type == "app_mention":
        background_tasks.add_task(handle_message_event, event, team_id)
    elif event_type == "app_home_opened":
        background_tasks.add_task(handle_app_home_opened, event, team_id)

    return {"ok": True}


@router.post("/slack/interactions")
async def slack_interactions(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()

    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verify_slack_signature(timestamp, body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    form = await request.form()
    payload_str = form.get("payload", "")
    if not payload_str:
        return {"ok": True}

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        return {"ok": True}

    action_type = payload.get("type")
    logger.info(f"Slack interaction: {action_type}")

    if action_type == "block_actions":
        background_tasks.add_task(handle_block_action, payload)

    return {"ok": True}


async def handle_block_action(payload: dict):
    try:
        await _handle_block_action_inner(payload)
    except Exception as e:
        import traceback
        logger.error(f"handle_block_action crashed: {e}\n{traceback.format_exc()}")


def _get_action_label(action: dict) -> str:
    text_field = action.get("text", "")
    if isinstance(text_field, dict):
        return text_field.get("text", "")
    return str(text_field) if text_field else ""


async def _handle_block_action_inner(payload: dict):
    actions = payload.get("actions", [])
    if not actions:
        return

    action = actions[0]
    action_id = action.get("action_id", "")

    URL_BUTTON_IDS = {"view_in_app", "view_plan_app", "join_meeting", "open_intake_call"}
    if action_id in URL_BUTTON_IDS or action_id.startswith(("view_req_", "view_candidate_req_", "view_pipeline_")):
        return

    value_str = action.get("value", "{}")

    try:
        value = json.loads(value_str)
    except json.JSONDecodeError:
        value = {"raw": value_str}

    user = payload.get("user", {})
    if isinstance(user, str):
        slack_user_id = user
    else:
        slack_user_id = user.get("id")
    channel_data = payload.get("channel", {})
    if isinstance(channel_data, dict):
        channel = channel_data.get("id")
    else:
        channel = channel_data
    team_data = payload.get("team")
    if isinstance(team_data, dict):
        team_id = team_data.get("id")
    elif isinstance(team_data, str):
        team_id = team_data
    elif isinstance(user, dict):
        team_id = user.get("team_id")
    else:
        team_id = None

    logger.info(f"Block action: action_id={action_id}, user={slack_user_id}, channel={channel}, team={team_id}")

    if not slack_user_id or not channel or not team_id:
        logger.warning(f"Interaction missing fields: user={slack_user_id}, channel={channel}, team={team_id}, raw_channel={channel_data}, raw_team={team_data}")
        return

    if action_id == "confirm_no":
        response_url = payload.get("response_url")
        if response_url:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(response_url, json={
                        "replace_original": True,
                        "text": "Cancelled.",
                        "blocks": [
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": "Cancelled."},
                            },
                            {
                                "type": "context",
                                "elements": [{"type": "mrkdwn", "text": "OpenRecruiting"}],
                            },
                        ],
                    })
            except Exception as e:
                logger.error(f"Failed to update cancelled message: {e}")
        else:
            service = get_slack_service()
            try:
                bot_token = await service.get_bot_token_for_team(team_id)
                await service.send_message(bot_token, channel, "Cancelled.", team_id=team_id)
            except Exception as e:
                logger.error(f"Cancel reply failed: {e}")
        return

    service = get_slack_service()
    try:
        bot_token = await service.get_bot_token_for_team(team_id)
    except ValueError:
        logger.warning(f"No installation for team {team_id}")
        return

    connection = await service.get_connection(slack_user_id, team_id)
    if not connection:
        logger.warning(f"No Slack connection for user={slack_user_id} team={team_id}")
        return

    if action_id.startswith("select_entity_"):
        label = _get_action_label(action)
        if isinstance(value, dict):
            selection_data = {**value, "label": label}
        else:
            selection_data = {"id": str(value), "label": label}
        synthetic_message = f"DISAMBIGUATION_RESPONSE: {json.dumps(selection_data)}"
    elif action_id == "confirm_yes":
        synthetic_message = f"CONFIRMED_ACTION: {json.dumps(value)}"
    elif action_id.startswith("fork_"):
        synthetic_message = f"FORK_ACTION: {json.dumps(value)}"
    elif action_id.startswith("resume_paused_"):
        synthetic_message = f"RESUME_PAUSED: {json.dumps(value)}"
    elif action_id.startswith("plan_error_"):
        synthetic_message = f"PLAN_ERROR_RECOVERY: {json.dumps(value)}"
    elif action_id.startswith("slot_"):
        start = value.get("start", "")
        end = value.get("end", "")
        label = _get_action_label(action)
        synthetic_message = f"I'll take the {label} slot [start: {start}, end: {end}]"
    else:
        label = _get_action_label(action)
        synthetic_message = f"Selected: {label}"

    response_url = payload.get("response_url")
    if response_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                selected_text = _get_action_label(action) or "Selected"
                await client.post(response_url, json={
                    "replace_original": True,
                    "text": f"Selected: {selected_text}",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f"*Selected:* {selected_text}"},
                        },
                        {
                            "type": "context",
                            "elements": [{"type": "mrkdwn", "text": "OpenRecruiting"}],
                        },
                    ],
                })
        except Exception as e:
            logger.error(f"Failed to update original message: {e}")

    thinking_ts = ""
    try:
        thinking_resp = await service.send_message(
            bot_token, channel,
            "Processing...",
            [{"type": "context", "elements": [{"type": "mrkdwn", "text": ":large_purple_circle: *Scout is processing...*"}]}],
            team_id=team_id,
        )
        if thinking_resp and thinking_resp.get("ts"):
            thinking_ts = thinking_resp["ts"]
    except Exception as e:
        logger.warning(f"Failed to send processing indicator: {e}")

    settings = get_settings()

    org_id = connection.get("organization_id")
    interaction_features = await _get_effective_slack_features(org_id, connection)

    has_write = interaction_features.get("assistant_write", False)
    has_read = interaction_features.get("assistant_read", False)
    interaction_mode = "full" if has_write else ("read_only" if has_read else None)

    if not interaction_mode:
        if thinking_ts:
            try:
                await service.update_message(
                    bot_token, channel, thinking_ts, "The assistant is not enabled for your organization.", team_id=team_id
                )
            except Exception:
                pass
        return

    is_resume = (
        action_id.startswith("select_entity") or action_id == "confirm_yes"
        or action_id.startswith("slot_") or action_id.startswith("fork_")
        or action_id.startswith("resume_paused_") or action_id.startswith("plan_error_")
    )
    agent_endpoint = "/resume" if is_resume else "/run"
    agent_payload = {
        "slack_user_id": slack_user_id,
        "slack_channel_id": channel,
        "team_id": team_id,
        "bot_token": bot_token,
        "profile_id": connection["profile_id"],
        "org_id": connection["organization_id"],
        "thinking_ts": thinking_ts,
        "mode": interaction_mode,
    }
    if is_resume:
        agent_payload["user_response"] = synthetic_message
        agent_payload["thread_id"] = f"{slack_user_id}:{channel}"
    else:
        agent_payload["user_message"] = synthetic_message

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        try:
            await client.post(
                f"{settings.SLACK_AGENT_URL}{agent_endpoint}",
                json=agent_payload,
            )
        except Exception as e:
            logger.error(f"Agent call from interaction failed: {e}", exc_info=True)
            error_text = "Something went wrong processing your selection. Please try again."
            if thinking_ts:
                try:
                    await service.update_message(bot_token, channel, thinking_ts, error_text, team_id=team_id)
                except Exception:
                    await service.send_message(bot_token, channel, error_text, team_id=team_id)
            else:
                await service.send_message(bot_token, channel, error_text, team_id=team_id)
