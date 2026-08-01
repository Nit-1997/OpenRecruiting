import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")

from fastapi import FastAPI

from src.config import get_settings
from src.logging import configure_logging

from local.api.routes import (
    complete_router,
    evidence_router,
    feedback_router,
    health_router,
    judge_router,
    rounds_router,
    topics_router,
)

settings = get_settings()
configure_logging(level=settings.log_level, format=settings.log_format)

app = FastAPI(title="Feedback Agent API (Local)")

app.include_router(health_router)
app.include_router(topics_router)
app.include_router(feedback_router)
app.include_router(complete_router)
app.include_router(evidence_router)
app.include_router(judge_router)
app.include_router(rounds_router)


@app.get("/")
def root():
    return {
        "message": "Feedback Agent API (Local)",
        "endpoints": [
            "/map-topics",
            "/process-feedback",
            "/process-complete",
            "/extract-evidence",
            "/judge-feedback",
            "/rounds",
            "/rounds/{id}",
            "/rounds/{id}/process",
            "/health",
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.api_port)
