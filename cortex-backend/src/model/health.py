from pydantic import BaseModel


class DependencyStatus(BaseModel):
    status: str


class HealthResponse(BaseModel):
    status: str
    version: str
    dependencies: dict[str, DependencyStatus]
