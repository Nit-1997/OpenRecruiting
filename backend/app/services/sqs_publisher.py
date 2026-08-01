import asyncio
import json
import logging
import boto3
from botocore.exceptions import ClientError
from app.config import get_settings

logger = logging.getLogger(__name__)

_sqs_client = None


def _get_sqs_client():
    global _sqs_client
    if _sqs_client is None:
        settings = get_settings()
        _sqs_client = boto3.client("sqs", region_name=settings.SQS_REGION or "us-west-1")
    return _sqs_client


async def publish_event(event_type: str, data: dict) -> bool:
    settings = get_settings()
    queue_url = settings.SQS_QUEUE_URL

    if not queue_url:
        logger.debug(f"SQS not configured, skipping event: {event_type}")
        return False

    message = {
        "event_type": event_type,
        **data,
    }

    try:
        client = _get_sqs_client()
        # boto3 send_message is a blocking network call — offload off the event
        # loop so async callers don't stall (BE-A1).
        await asyncio.to_thread(
            client.send_message,
            QueueUrl=queue_url,
            MessageBody=json.dumps(message),
            MessageGroupId=data.get("organization_id", "default"),
        )
        logger.info(f"Published SQS event: {event_type}")
        return True
    except ClientError as e:
        logger.error(f"Failed to publish SQS event {event_type}: {e}")
        return False
