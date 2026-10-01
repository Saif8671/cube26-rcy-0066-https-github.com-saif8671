
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from app.core.config import settings
from app.core.logging import logger


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""
    pass


# Connection pool configuration suitable for Supabase / PostgreSQL small instances
engine = create_engine(
    settings.database_url,
    connect_args={"connect_timeout": 5},
    pool_pre_ping=True,       # Detect disconnects before issuing queries
    pool_size=2,              # Demo-safe steady connection pool
    max_overflow=0,            # Keep connection use bounded for the demo
    pool_recycle=1800,        # Recycle connections every 30 minutes to avoid stale sockets
    pool_timeout=10,          # Seconds to wait before timing out on pool checkout
)

from sqlalchemy import event


@event.listens_for(engine, "checkin")
def receive_checkin(dbapi_connection, connection_record):
    """Ensure any checked-in connection is fully reset back to default role and clear org setting."""
    try:
        with dbapi_connection.cursor() as cur:
            cur.execute("RESET ROLE; RESET app.current_org;")
        dbapi_connection.commit()
    except Exception:
        pass


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


from fastapi import Request


DENY_ORG_SENTINEL = "__DENY_NO_ORG_MATCH__"


def set_org_context(db: Session, org_id: str | None) -> None:
    """
    Explicitly set PostgreSQL session context enforcing multi-tenant row-level security (RLS).
    Switches session role to 'authenticated' (rolbypassrls=False) and assigns 'app.current_org'.
    If org_id is empty or None, sets to a non-matching sentinel so RLS denies all access (DEFAULT DENY).
    Engineering Rule 1: Scoped to the organisation, enabled and forced.
    """
    clean_org = (org_id or "").strip() or DENY_ORG_SENTINEL
    db.execute(text("SET ROLE authenticated;"))
    db.execute(text("SELECT set_config('app.current_org', :org_id, false);"), {"org_id": clean_org})


def current_org(db: Session) -> str | None:
    """
    Return the active organization ID from the PostgreSQL session setting 'app.current_org'.
    Returns None if not set, empty, or set to DENY_ORG_SENTINEL.
    """
    try:
        val = db.execute(text("SELECT current_setting('app.current_org', true);")).scalar()
        if not val:
            return None
        val_str = str(val).strip()
        if not val_str or val_str == DENY_ORG_SENTINEL:
            return None
        return val_str
    except Exception:
        return None


def reset_org_context(db: Session) -> None:
    """Reset PostgreSQL session context back to default role and clear org setting."""
    try:
        db.execute(text("RESET ROLE;"))
        db.execute(text("RESET app.current_org;"))
        db.commit()
    except Exception:
        try:
            db.rollback()
            db.execute(text("RESET ROLE;"))
            db.execute(text("RESET app.current_org;"))
            db.commit()
        except Exception:
            pass


def get_db(request: Request = None) -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding a managed database session with multi-tenancy RLS context.
    Reads org context from 'X-Org-Id' header or 'org_id' query parameter.
    DEFAULT BEHAVIOR WHEN NO ORG CONTEXT IS SUPPLIED: DENY (role 'authenticated' with non-matching sentinel).
    The connection NEVER remains on the superuser/bypass role for a normal API request under any circumstance.
    """
    db = SessionLocal()
    logger.info("database session open")
    org_id = None
    if request is not None:
        try:
            org_id = request.headers.get("x-org-id") or request.query_params.get("org_id")
        except Exception:
            pass
    try:
        set_org_context(db, org_id)
        yield db
    finally:
        reset_org_context(db)
        db.close()
        logger.info("database session close")


def check_database_connection(timeout_seconds: float = 3.0) -> bool:
    """
    Safely ping the database with a fast timeout.
    Returns True if connection succeeds, False otherwise.
    Does not crash the application if the database is unreachable.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
            return True
    except Exception as exc:
        logger.warning(f"Database health check ping failed: {exc.__class__.__name__}")
        return False
