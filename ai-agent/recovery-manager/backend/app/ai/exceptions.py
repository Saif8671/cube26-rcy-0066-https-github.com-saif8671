"""Custom exceptions for Phase 5 AI Reasoning / Recovery Assessment."""


class AIError(Exception):
    """Base exception for all AI reasoning errors."""
    pass


class AIConfigurationError(AIError):
    """Raised when the AI client or settings are misconfigured (e.g. missing API key)."""
    pass


class AIProviderError(AIError):
    """Raised when external AI provider fails or returns unhandled error."""
    pass


class AIOutputValidationError(AIError):
    """Raised when the AI output is malformed, invalid JSON, or violates schema."""
    pass


class InvalidEvidenceIDError(AIOutputValidationError):
    """Raised when the AI returns an evidence ID not present in supplied evidence."""
    pass


class ClaimAmountValidationError(AIOutputValidationError):
    """Raised when claim_amount or claim_supported violates business invariants."""
    pass
