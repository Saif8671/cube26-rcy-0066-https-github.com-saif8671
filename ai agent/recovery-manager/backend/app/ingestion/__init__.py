"""Ingestion module for Recovery Manager."""

from app.ingestion.exceptions import (
    IngestionError,
    UnsupportedFormatError,
    MalformedFileError,
    EmptyFileError,
    RecordValidationError,
    IdentifierResolutionError,
    DuplicateRecordError,
)
from app.ingestion.readers import read_file, read_csv, read_xlsx, read_json
from app.ingestion.service import (
    IngestionService,
    IngestionResult,
    IngestionErrorDetail,
    ingestion_service,
)

__all__ = [
    "IngestionError",
    "UnsupportedFormatError",
    "MalformedFileError",
    "EmptyFileError",
    "RecordValidationError",
    "IdentifierResolutionError",
    "DuplicateRecordError",
    "read_file",
    "read_csv",
    "read_xlsx",
    "read_json",
    "IngestionService",
    "IngestionResult",
    "IngestionErrorDetail",
    "ingestion_service",
]
