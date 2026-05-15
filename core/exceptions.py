"""
Domain exceptions. All application-level errors derive from DomainError.

Using a hierarchy lets callers catch at any granularity:
  - catch DomainError for any business rule violation
  - catch NotFoundError specifically for missing resources
  - catch AuthenticationError specifically for login failures
"""


class DomainError(Exception):
    """Base for all domain-level errors."""


class NotFoundError(DomainError):
    """A required resource does not exist."""

    def __init__(self, resource: str, identifier):
        super().__init__(f"{resource} not found: {identifier!r}")
        self.resource = resource
        self.identifier = identifier


class AlreadyExistsError(DomainError):
    """Attempt to create a resource that already exists."""

    def __init__(self, resource: str, identifier):
        super().__init__(f"{resource} already exists: {identifier!r}")
        self.resource = resource
        self.identifier = identifier


class AuthenticationError(DomainError):
    """Invalid credentials or account inactive."""


class AuthorizationError(DomainError):
    """Authenticated user does not have permission for this operation."""


class EnrollmentError(DomainError):
    """Violation of enrollment business rules."""


class AttendanceError(DomainError):
    """Violation of attendance business rules."""


class RegistrationError(DomainError):
    """Face registration failed (no faces detected, bad images, etc.)."""


class EncryptionError(DomainError):
    """Encryption or decryption failed."""


class ValidationError(DomainError):
    """Input data failed validation."""

    def __init__(self, field: str, message: str):
        super().__init__(f"validation error on {field!r}: {message}")
        self.field = field
        self.message = message
