"""
Slack Block Kit message templates for v2.

DELIBERATE DUPLICATION: ported from backend/v1/app/services/slack_blocks.py.
Keep in lockstep when either changes.
"""


def welcome_blocks(user_name: str = "there") -> list:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Hey {user_name}! :wave: I'm Scout, your AI recruiting assistant.\n\nYour Slack workspace is now connected. You can manage requisitions, candidates, interviews, scorecards, and scheduling — right here in Slack.",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":zap: *Try it out:* Ask me things like _\"Show me my requisitions\"_, _\"Schedule an interview for Nitin\"_, or _\"What's the pipeline status?\"_",
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Visit <http://localhost:3005/dashboard|localhost:3005> for the full dashboard",
                }
            ],
        },
    ]


def home_tab_blocks(org_name: str = None) -> list:
    greeting = f"Welcome, *{org_name}*!" if org_name else "Welcome to OpenRecruiting!"
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "OpenRecruiting"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{greeting}\n\nOpenRecruiting is your AI recruiting assistant. Ask me to manage requisitions, candidates, interviews, and scheduling — all from Slack.",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open Dashboard"},
                    "url": "http://localhost:3005/dashboard",
                    "action_id": "open_dashboard",
                }
            ],
        },
    ]


def error_blocks(message: str) -> list:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: {message}",
            },
        },
    ]
