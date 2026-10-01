"""Read-only DB check using the app's configured settings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import engine


url = make_url(settings.database_url)
print(f"host={url.host}")
print(f"database={url.database}")
try:
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT COALESCE(state, 'unknown') AS state, count(*)
            FROM pg_stat_activity
            WHERE datname = current_database()
            GROUP BY state
            ORDER BY state
        """)).all()
        print("connection_state_counts=" + ",".join(f"{state}:{count}" for state, count in rows) or "connection_state_counts=")
except Exception as exc:
    print(f"connection_state_counts=unavailable:{type(exc).__name__}")
