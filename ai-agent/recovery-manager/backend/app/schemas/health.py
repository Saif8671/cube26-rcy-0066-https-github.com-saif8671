from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Structured health check response model."""
    status: str = Field(..., description="Overall health status: 'ok' or 'degraded'")
    database: str = Field(..., description="Database connectivity: 'connected' or 'disconnected'")
    version: str = Field(default="0.1.0", description="Backend service version")
    environment: str = Field(default="development", description="Runtime environment")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "ok",
                "database": "connected",
                "version": "0.1.0",
                "environment": "development",
            }
        }
    }
