import os
from pathlib import Path
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings loaded from environment or .env file."""

    # Database
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/recovery_manager",
        description="PostgreSQL / Supabase connection URL",
    )

    # Supabase
    supabase_url: Optional[str] = Field(default=None, description="Supabase project API URL")
    supabase_key: Optional[str] = Field(default=None, description="Supabase service/anon key")

    # AI Provider
    anthropic_api_key: Optional[str] = Field(default=None, description="Anthropic API Key for AI reasoning")
    anthropic_model: str = Field(default="claude-3-5-sonnet-20241022", description="Anthropic model for AI reasoning")

    # Gemini AI Provider
    # Model choice: gemini-3.5-flash-lite
    # Rationale: Extremely fast, cost-efficient, high availability flash tier model with native structured
    # schema support and separate free tier rate limits, ideal for high-volume automated charge recovery assessment. Swappable via config/env.
    gemini_api_key: Optional[str] = Field(default=None, validation_alias="GEMINI_API_KEY", description="Google Gemini API Key for AI reasoning")
    gemini_model: str = Field(default="gemini-3.5-flash-lite", validation_alias="GEMINI_MODEL", description="Gemini model for AI reasoning")

    # Backend
    backend_port: int = Field(default=8000, description="Server port")
    backend_env: str = Field(default="development", description="Environment: development, staging, production")

    # CORS Configuration (environment-driven, defaults to '*' for development)
    allowed_origins: str = Field(
        default="*",
        validation_alias="ALLOWED_ORIGINS",
        description="Comma-separated allowed origins (e.g. 'https://frontend.vercel.app') or '*' for local development",
    )

    @property
    def cors_origins(self) -> list[str]:
        """Parse allowed_origins into a list, maintaining local development compatibility."""
        if not self.allowed_origins or self.allowed_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    # App metadata
    app_name: str = "Recovery Manager API"
    app_version: str = "0.1.0"

    model_config = SettingsConfigDict(
        env_file=(
            str(Path(__file__).resolve().parent.parent.parent / ".env"),
            str(Path(__file__).resolve().parent.parent.parent.parent / ".env"),
            ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """Ensure standard postgresql:// URI scheme required by SQLAlchemy."""
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v

    def safe_dict(self) -> dict:
        """Return non-sensitive settings dictionary safe for logging."""
        return {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "backend_env": self.backend_env,
            "backend_port": self.backend_port,
            "database_configured": bool(self.database_url),
            "supabase_configured": bool(self.supabase_url and self.supabase_key),
            "anthropic_configured": bool(self.anthropic_api_key),
            "gemini_configured": bool(self.gemini_api_key),
        }


settings = Settings()
