"""
Custom exception handler for DRF.

Translates domain exceptions into proper HTTP responses
without exposing Django tracebacks or internal details.
"""
import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

from traffic.domain.exceptions import (
    DomainError,
    SafetyViolationError,
    InvalidTransitionError,
    InvalidCommandError,
    DuplicateEventError,
    InvalidEventError,
    ControllerUncertainError,
    StaleOperationError,
    JunctionNotFoundError,
)

logger = logging.getLogger('traffic.api')


def custom_exception_handler(exc, context):
    """Map domain exceptions to HTTP responses."""

    # Let DRF handle its own exceptions first
    response = exception_handler(exc, context)
    if response is not None:
        return response

    # Map domain exceptions
    if isinstance(exc, JunctionNotFoundError):
        return Response(
            {'error': str(exc), 'code': 'NOT_FOUND'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, DuplicateEventError):
        return Response(
            {'error': str(exc), 'code': 'DUPLICATE'},
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, InvalidEventError):
        return Response(
            {'error': str(exc), 'code': 'INVALID_EVENT'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, InvalidCommandError):
        return Response(
            {'error': str(exc), 'code': 'INVALID_COMMAND'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, InvalidTransitionError):
        return Response(
            {'error': str(exc), 'code': 'INVALID_TRANSITION'},
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, SafetyViolationError):
        logger.critical(f"Safety violation: {exc}")
        return Response(
            {'error': 'Safety violation detected. Operation rejected.', 'code': 'SAFETY_VIOLATION'},
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, ControllerUncertainError):
        return Response(
            {'error': str(exc), 'code': 'CONTROLLER_UNCERTAIN'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if isinstance(exc, StaleOperationError):
        return Response(
            {'error': str(exc), 'code': 'STALE_OPERATION'},
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, DomainError):
        return Response(
            {'error': str(exc), 'code': 'DOMAIN_ERROR'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Unexpected errors — don't expose internals
    logger.exception(f"Unexpected error: {exc}")
    return Response(
        {'error': 'An internal error occurred.', 'code': 'INTERNAL_ERROR'},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )

