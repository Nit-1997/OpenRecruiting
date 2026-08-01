import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")

from fastapi import FastAPI

from src.config import get_settings
from src.logging import configure_logging

settings = get_settings()
configure_logging(level=settings.log_level, format=settings.log_format)

app = FastAPI(title="Intake Agent API (Local)")

from local.api.routes import process_router, health_router

app.include_router(health_router)
app.include_router(process_router)


@app.get("/")
def root():
    return {
        "message": "Intake Agent API (Local)",
        "endpoints": [
            "/process",
            "/health",
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)
