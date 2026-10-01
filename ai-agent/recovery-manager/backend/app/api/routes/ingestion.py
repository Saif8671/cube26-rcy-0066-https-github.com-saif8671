"""API routes strictly limited to Phase 3 ingestion."""

from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import logger
from app.ingestion.exceptions import (
    EmptyFileError,
    MalformedFileError,
    UnsupportedFormatError,
    IngestionError,
)
from app.ingestion.service import ingestion_service
from app.schemas.ingestion import IngestionResponseSchema

router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB limit to prevent heap exhaustion / DoS


async def _read_upload_file(upload: UploadFile) -> bytes:
    """Read upload file stream in chunks enforcing MAX_FILE_SIZE."""
    chunk_size = 1024 * 1024  # 1MB
    content = bytearray()
    while chunk := await upload.read(chunk_size):
        content.extend(chunk)
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds maximum allowed limit of 10MB ({MAX_FILE_SIZE} bytes).",
            )
    return bytes(content)


async def _extract_content(
    request: Request,
    file: Optional[UploadFile] = None,
) -> tuple[Optional[bytes], Optional[str], Optional[List[Dict[str, Any]]]]:
    """
    Extract file bytes + filename or parsed JSON records from the incoming request.
    Supports multipart form file upload, octet-stream, or application/json.
    Enforces MAX_FILE_SIZE (10MB) across all upload vectors.
    """
    content_type = request.headers.get("content-type", "")

    # Pre-check content-length if available
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File size exceeds maximum allowed limit of 10MB ({MAX_FILE_SIZE} bytes).",
                )
        except (ValueError, TypeError):
            pass

    # 1. Direct UploadFile parameter
    if file is not None:
        file_bytes = await _read_upload_file(file)
        return file_bytes, file.filename, None

    # 2. Multipart form data
    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded = form.get("file")
        if isinstance(uploaded, UploadFile):
            file_bytes = await _read_upload_file(uploaded)
            return file_bytes, uploaded.filename, None
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Multipart request missing 'file' field",
        )

    # 3. JSON body
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception as exc:
            raise MalformedFileError(f"Malformed JSON body: {exc}") from exc

        if isinstance(body, list):
            if not body:
                raise EmptyFileError("JSON list contains no records")
            return None, None, body
        elif isinstance(body, dict):
            if "records" in body and isinstance(body["records"], list):
                if not body["records"]:
                    raise EmptyFileError("Records array is empty")
                return None, None, body["records"]
            return None, None, [body]
        else:
            raise MalformedFileError("JSON root must be an array or object")

    # 4. Fallback raw body if filename provided in header or query
    body_bytes = await request.body()
    if body_bytes:
        if len(body_bytes) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds maximum allowed limit of 10MB ({MAX_FILE_SIZE} bytes).",
            )
        filename_header = request.headers.get("x-filename")
        return body_bytes, filename_header, None

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Missing request payload. Provide a file upload or JSON body.",
    )


@router.post("/charges", response_model=IngestionResponseSchema)
async def ingest_charges_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    source_report: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Ingest charges from CSV, XLSX, or JSON file upload or direct JSON body.
    """
    try:
        file_bytes, filename, records = await _extract_content(request, file)

        if records is not None:
            result = await run_in_threadpool(
                ingestion_service.ingest_charges_records,
                records=records, db=db, source_report=source_report or "direct_json",
                auto_create_containers=True,
            )
        elif file_bytes is not None:
            result = await run_in_threadpool(
                ingestion_service.ingest_charges,
                source=file_bytes, db=db, source_report=source_report, filename=filename,
                auto_create_containers=True,
            )
        else:
            raise EmptyFileError("No charge records provided")

        return result.to_dict()

    except (EmptyFileError, MalformedFileError, UnsupportedFormatError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/reimbursements", response_model=IngestionResponseSchema)
async def ingest_reimbursements_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    source_report: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Ingest reimbursements from CSV, XLSX, or JSON file upload or direct JSON body.
    """
    try:
        file_bytes, filename, records = await _extract_content(request, file)

        if records is not None:
            result = await run_in_threadpool(
                ingestion_service.ingest_reimbursements_records,
                records=records, db=db, source_report=source_report or "direct_json",
            )
        elif file_bytes is not None:
            result = await run_in_threadpool(
                ingestion_service.ingest_reimbursements,
                source=file_bytes, db=db, source_report=source_report, filename=filename,
            )
        else:
            raise EmptyFileError("No reimbursement records provided")

        return result.to_dict()

    except (EmptyFileError, MalformedFileError, UnsupportedFormatError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/evidence", response_model=IngestionResponseSchema)
async def ingest_evidence_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    source_report: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Ingest operational evidence from CSV, XLSX, or JSON file upload or direct JSON body.
    Auto-detects Receiving, Prep, Pack, or Returns pod layout.
    """
    try:
        file_bytes, filename, records = await _extract_content(request, file)

        if records is not None:
            result = await run_in_threadpool(
                ingestion_service.ingest_evidence_records,
                records=records, db=db, source_report=source_report or "direct_json",
                auto_create_containers=True,
            )
        elif file_bytes is not None:
            result = await run_in_threadpool(
                ingestion_service.ingest_evidence,
                source=file_bytes, db=db, source_report=source_report, filename=filename,
                auto_create_containers=True,
            )
        else:
            raise EmptyFileError("No evidence records provided")

        return result.to_dict()

    except (EmptyFileError, MalformedFileError, UnsupportedFormatError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/evidence/receiving", response_model=IngestionResponseSchema)
async def ingest_receiving_evidence_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    source_report: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Ingest Receiving manager evidence specifically."""
    try:
        file_bytes, filename, records = await _extract_content(request, file)
        if records is not None:
            from app.ingestion.normalizers import normalize_receiving_evidence
            records = [normalize_receiving_evidence(r) for r in records]
            result = await run_in_threadpool(ingestion_service.ingest_evidence_records, records=records, db=db, source_report=source_report or "receiving_sample.csv", auto_create_containers=True)
        elif file_bytes is not None:
            result = await run_in_threadpool(ingestion_service.ingest_receiving_evidence, source=file_bytes, db=db, source_report=source_report, filename=filename)
        else:
            raise EmptyFileError("No receiving records provided")
        return result.to_dict()
    except (EmptyFileError, MalformedFileError, UnsupportedFormatError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/evidence/prep", response_model=IngestionResponseSchema)
async def ingest_prep_evidence_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    source_report: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Ingest Prep manager evidence specifically."""
    try:
        file_bytes, filename, records = await _extract_content(request, file)
        if records is not None:
            from app.ingestion.normalizers import normalize_prep_evidence
            records = [normalize_prep_evidence(r) for r in records]
            result = await run_in_threadpool(ingestion_service.ingest_evidence_records, records=records, db=db, source_report=source_report or "prep_sample.csv", auto_create_containers=True)
        elif file_bytes is not None:
            result = await run_in_threadpool(ingestion_service.ingest_prep_evidence, source=file_bytes, db=db, source_report=source_report, filename=filename)
        else:
            raise EmptyFileError("No prep records provided")
        return result.to_dict()
    except (EmptyFileError, MalformedFileError, UnsupportedFormatError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/evidence/pack", response_model=IngestionResponseSchema)
async def ingest_pack_evidence_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    source_report: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Ingest Pack manager evidence specifically."""
    try:
        file_bytes, filename, records = await _extract_content(request, file)
        if records is not None:
            from app.ingestion.normalizers import normalize_pack_evidence
            records = [normalize_pack_evidence(r) for r in records]
            result = await run_in_threadpool(ingestion_service.ingest_evidence_records, records=records, db=db, source_report=source_report or "pack_sample.csv", auto_create_containers=True)
        elif file_bytes is not None:
            result = await run_in_threadpool(ingestion_service.ingest_pack_evidence, source=file_bytes, db=db, source_report=source_report, filename=filename)
        else:
            raise EmptyFileError("No pack records provided")
        return result.to_dict()
    except (EmptyFileError, MalformedFileError, UnsupportedFormatError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/evidence/returns", response_model=IngestionResponseSchema)
async def ingest_returns_evidence_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    source_report: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Ingest Returns manager evidence specifically."""
    try:
        file_bytes, filename, records = await _extract_content(request, file)
        if records is not None:
            from app.ingestion.normalizers import normalize_returns_evidence
            records = [normalize_returns_evidence(r) for r in records]
            result = await run_in_threadpool(ingestion_service.ingest_evidence_records, records=records, db=db, source_report=source_report or "returns_sample.csv", auto_create_containers=True)
        elif file_bytes is not None:
            result = await run_in_threadpool(ingestion_service.ingest_returns_evidence, source=file_bytes, db=db, source_report=source_report, filename=filename)
        else:
            raise EmptyFileError("No returns records provided")
        return result.to_dict()
    except (EmptyFileError, MalformedFileError, UnsupportedFormatError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
