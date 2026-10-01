"""Ingestion-specific exceptions for Recovery Manager."""

from typing import Optional


class IngestionError(Exception):
    """Base exception for all ingestion failures."""
    pass


class UnsupportedFormatError(IngestionError):
    """Raised when an unsupported file extension or format is encountered."""
    pass


class MalformedFileError(IngestionError):
    """Raised when a file cannot be parsed due to corrupt syntax or decoding failure."""
    pass


class EmptyFileError(IngestionError):
    """Raised when an ingested file or record set contains no data records."""
    pass


class RecordValidationError(IngestionError):
    """Raised when a single record violates schema, type, or constraint requirements."""

    def __init__(
        self,
        message: str,
        row_index: Optional[int] = None,
        field: Optional[str] = None,
        identifier: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.row_index = row_index
        self.field = field
        self.identifier = identifier


class IdentifierResolutionError(IngestionError):
    """Raised when an explicit foreign key reference cannot be resolved in the database."""

    def __init__(
        self,
        message: str,
        identifier: Optional[str] = None,
        target_table: Optional[str] = None,
        row_index: Optional[int] = None,
    ):
        super().__init__(message)
        self.message = message
        self.identifier = identifier
        self.target_table = target_table
        self.row_index = row_index


class DuplicateRecordError(IngestionError):
    """Raised when a unique business identifier already exists in the database or batch."""

    def __init__(
        self,
        message: str,
        identifier: Optional[str] = None,
        record_type: Optional[str] = None,
        row_index: Optional[int] = None,
    ):
        super().__init__(message)
        self.message = message
        self.identifier = identifier
        self.record_type = record_type
        self.row_index = row_index
