from .health import router as health_router
from .topics import router as topics_router
from .feedback import router as feedback_router
from .complete import router as complete_router
from .evidence import router as evidence_router
from .judge import router as judge_router
from .rounds import router as rounds_router

__all__ = [
    "health_router",
    "topics_router",
    "feedback_router",
    "complete_router",
    "evidence_router",
    "judge_router",
    "rounds_router",
]
