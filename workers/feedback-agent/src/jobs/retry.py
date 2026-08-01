import asyncio
from functools import wraps

from src.logging import get_logger

logger = get_logger(__name__)


def with_retry(max_attempts: int = 3, backoff_factor: float = 2.0):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    wait_time = backoff_factor ** attempt
                    logger.warning(
                        "retry_attempt",
                        function=func.__name__,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        wait_time=wait_time,
                        error=str(e),
                    )
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(wait_time)

            raise last_exception

        return wrapper

    return decorator
