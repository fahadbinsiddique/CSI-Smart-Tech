"""
Domain exceptions for the Factory Traffic Management System.
Pure Python — no framework dependencies.
"""


class DomainError(Exception):
    """Base exception for domain errors."""
    pass


class SafetyViolationError(DomainError):
    """Raised when an operation would violate a traffic safety invariant."""
    pass


class InvalidTransitionError(DomainError):
    """Raised when a state transition is not valid from the current state."""
    pass


class InvalidCommandError(DomainError):
    """Raised when a command is invalid (e.g. unknown direction for phase)."""
    pass


class DuplicateEventError(DomainError):
    """Raised when a duplicate event is detected."""
    pass


class InvalidEventError(DomainError):
    """Raised when an event payload is invalid."""
    pass


class ControllerUncertainError(DomainError):
    """Raised when controller state is uncertain and operation requires certainty."""
    pass


class StaleOperationError(DomainError):
    """Raised when an operation is based on stale state (optimistic concurrency)."""
    pass


class JunctionNotFoundError(DomainError):
    """Raised when a referenced junction does not exist."""
    pass

