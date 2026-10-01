"""Exceptions for Phase 6 Deterministic Rule Validation."""


class RuleValidationError(Exception):
    """Base exception for Phase 6 rule validation errors."""
    pass


class OperationalBlockingError(RuleValidationError):
    """Raised when operational state (e.g., duplicate, already reimbursed) blocks recovery."""
    pass


class EvidenceRuleError(RuleValidationError):
    """Raised when evidence validation fails (e.g., unknown IDs, missing evidence)."""
    pass


class FinancialRuleError(RuleValidationError):
    """Raised when monetary/amount validation fails (e.g., <=0, exceeds charge)."""
    pass


