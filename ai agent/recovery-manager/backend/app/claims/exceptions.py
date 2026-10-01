"""Exceptions for Phase 7 Claim Engine."""


class ClaimEngineError(Exception):
    """Base exception for Claim Engine errors."""
    pass


class ClaimIntegrityError(ClaimEngineError):
    """Raised when claim invariant or validation checks fail."""
    pass


class ClaimTransactionError(ClaimEngineError):
    """Raised when database transaction fails during claim persistence."""
    pass
