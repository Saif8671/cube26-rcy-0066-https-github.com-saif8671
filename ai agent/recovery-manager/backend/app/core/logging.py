import logging
import sys
import re

# Patterns to prevent accidental credential leakage in logs
SENSITIVE_PATTERNS = [
    re.compile(r"://([^:]+):([^@]+)@", re.IGNORECASE),  # Matches user:password@ in URIs
    re.compile(r"Bearer\s+[A-Za-z0-9\-_\.]+", re.IGNORECASE),
    re.compile(r"sk-ant-[A-Za-z0-9\-_]+", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"), # JWT tokens
]


class SensitiveDataFilter(logging.Filter):
    """Filter that scrubs credentials and sensitive tokens from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            # Redact URI passwords
            msg = SENSITIVE_PATTERNS[0].sub(r"://\1:***@", msg)
            # Redact Bearer tokens
            msg = SENSITIVE_PATTERNS[1].sub("Bearer ***", msg)
            # Redact Anthropic keys
            msg = SENSITIVE_PATTERNS[2].sub("sk-ant-***", msg)
            # Redact JWTs
            msg = SENSITIVE_PATTERNS[3].sub("***JWT_TOKEN***", msg)
            record.msg = msg
        return True


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure structured, sanitized logging for the application."""
    root_logger = logging.getLogger()
    
    # Avoid duplicate handlers on reload
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.addFilter(SensitiveDataFilter())
        root_logger.addHandler(handler)

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Silence overly verbose external loggers
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logger = logging.getLogger("recovery_manager")
    return logger


logger = setup_logging()
