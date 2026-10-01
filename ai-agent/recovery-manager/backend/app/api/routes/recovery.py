from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.deterministic_recovery import preview_recovery, run_recovery
from app.core.logging import logger

router = APIRouter(prefix="/recovery", tags=["Deterministic Recovery"])

@router.post("/run")
def run_recovery_endpoint(db: Session = Depends(get_db)):
    try:
        return run_recovery(db)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("recovery run failed type=%s message=%s sql=%s", type(exc).__name__, str(exc), getattr(exc, "statement", None))
        return JSONResponse(status_code=500, content={"error": "Database Error", "reason_code": "RECOVERY_DATABASE_ERROR"})
    except Exception as exc:
        db.rollback()
        logger.exception("recovery run failed type=%s message=%s sql=%s", type(exc).__name__, str(exc), getattr(exc, "statement", None))
        return JSONResponse(status_code=500, content={"error": "Recovery Error", "reason_code": "RECOVERY_ERROR"})


@router.get("/preview")
def preview_recovery_endpoint(db: Session = Depends(get_db)):
    try:
        return preview_recovery(db)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("recovery preview failed type=%s message=%s sql=%s", type(exc).__name__, str(exc), getattr(exc, "statement", None))
        return JSONResponse(status_code=500, content={"error": "Database Error", "reason_code": "RECOVERY_PREVIEW_DATABASE_ERROR"})
    except Exception as exc:
        db.rollback()
        logger.exception("recovery preview failed type=%s message=%s sql=%s", type(exc).__name__, str(exc), getattr(exc, "statement", None))
        return JSONResponse(status_code=500, content={"error": "Recovery Error", "reason_code": "RECOVERY_PREVIEW_ERROR"})
