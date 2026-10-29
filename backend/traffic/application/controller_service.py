"""
Controller service for handling controller events and acknowledgements.

Processes ACKs, validates them against pending commands, and updates
actual signal state. Handles controller online/offline events.
"""
import logging
from typing import Dict

from django.db import transaction
from django.utils import timezone

from traffic.domain.clock import Clock, SystemClock
from traffic.domain.enums import (
    AuditEventType,
    CommandStatus,
    DeviceHealth,
    OperatingMode,
    SignalState,
    TransitionState,
)
from traffic.domain.models import SignalVector
from traffic.domain.exceptions import InvalidCommandError
from traffic.infrastructure.repositories import (
    AuditRepository,
    CommandRepository,
    JunctionRepository,
    JunctionStateRepository,
)

logger = logging.getLogger('traffic.controller_service')


class ControllerService:
    """
    Application service for processing controller events.
    
    Handles:
    - ACK responses from physical controllers
    - Controller online/offline status changes
    - Actual state confirmation
    - Duplicate and stale ACK handling
    """

    def __init__(self, clock: Clock = None):
        self._clock = clock or SystemClock()
        self._junction_repo = JunctionRepository()
        self._state_repo = JunctionStateRepository()
        self._command_repo = CommandRepository()
        self._audit_repo = AuditRepository()

    def process_controller_event(self, data: dict) -> Dict:
        """
        Process a controller event (ACK, NACK, status change).
        """
        command_id = data.get('command_id')
        junction_id = data.get('junction_id')
        status = data.get('status')
        actual_state = data.get('actual_state')
        actual_signals = data.get('actual_signals')
        device_type = data.get('device_type')
        device_status = data.get('status')

        # Handle device status events (ONLINE/OFFLINE)
        if device_type:
            return self._handle_device_status(data)

        # Handle command ACK/NACK
        if command_id:
            return self._handle_command_ack(data)

        raise InvalidCommandError("Controller event must include command_id or device_type")

    def _handle_command_ack(self, data: dict) -> Dict:
        """Handle a controller command acknowledgement."""
        command_id = data.get('command_id')
        junction_id = data.get('junction_id')
        status = data.get('status', 'ACK')
        actual_state = data.get('actual_state')
        actual_signals_data = data.get('actual_signals')

        if not command_id:
            raise InvalidCommandError("Missing required field: command_id")

        with transaction.atomic():
            # Look up the command
            cmd = self._command_repo.get_by_command_id(command_id)

            if cmd is None:
                # Unknown command — reject
                logger.warning(f"ACK for unknown command: {command_id}")
                if junction_id:
                    try:
                        junction = self._junction_repo.get_by_id(junction_id)
                        self._audit_repo.log(
                            junction=junction,
                            event_type=AuditEventType.CONTROLLER_ACK_REJECTED.value,
                            command_id=command_id,
                            details={'reason': 'Unknown command_id'},
                            reason="ACK rejected: unknown command",
                        )
                    except Exception:
                        pass
                return {
                    'status': 'rejected',
                    'message': f'Unknown command_id: {command_id}',
                }

            junction = cmd.junction
            if not junction_id:
                junction_id = junction.junction_id

            # Check for duplicate or superseded ACK
            if cmd.status in [
                CommandStatus.ACKNOWLEDGED.value,
                CommandStatus.SUPERSEDED.value,
                CommandStatus.TIMED_OUT.value,
            ]:
                self._audit_repo.log(
                    junction=junction,
                    event_type=AuditEventType.CONTROLLER_ACK_REJECTED.value,
                    command_id=command_id,
                    details={
                        'current_status': cmd.status,
                        'reason': f'Command already {cmd.status}',
                    },
                    reason=f"Duplicate/stale ACK for {cmd.status} command",
                )
                return {
                    'status': 'rejected',
                    'message': f'Command {command_id} already {cmd.status}',
                }

            # Determine actual signals
            if actual_signals_data:
                confirmed_signals = actual_signals_data
            elif actual_state:
                # Single direction ACK — use requested signals as base
                confirmed_signals = cmd.requested_signals.copy()
                if cmd.direction:
                    confirmed_signals[cmd.direction] = actual_state
            else:
                # ACK without actual state — trust the requested signals
                confirmed_signals = cmd.requested_signals

            if status == 'ACK':
                # Safety: never treat a controller ACK as confirmation unless the
                # confirmed signals match the signals we commanded. A controller
                # that reports a different state has not executed our command —
                # accepting it would falsely represent physical state and could
                # mask a conflicting GREEN.
                signals_match = confirmed_signals == cmd.requested_signals

                # Update command status
                if signals_match:
                    self._command_repo.update_command_status(
                        command_id,
                        CommandStatus.ACKNOWLEDGED,
                        actual_signals=confirmed_signals,
                    )
                else:
                    self._command_repo.update_command_status(
                        command_id,
                        CommandStatus.FAILED,
                        actual_signals=confirmed_signals,
                        failure_reason=(
                            "ACK signal mismatch: controller confirmed "
                            f"{confirmed_signals} but command requested "
                            f"{cmd.requested_signals}"
                        ),
                    )

                # Update actual signals in junction state only when the
                # controller confirms exactly what was commanded. On mismatch
                # the last controller-confirmed state is preserved so the
                # desired/actual mismatch remains visible to operators.
                state = self._state_repo.get_snapshot(junction_id)

                new_actual = SignalVector.from_dict(confirmed_signals) if signals_match else None

                update_kwargs = {
                    'junction_id': junction_id,
                    'expected_version': state.version,
                    'controller_health': DeviceHealth.ONLINE if signals_match else DeviceHealth.WARNING,
                }
                if new_actual is not None:
                    update_kwargs['actual_signals'] = new_actual

                self._state_repo.update_state(**update_kwargs)

                self._audit_repo.log(
                    junction=junction,
                    event_type=(
                        AuditEventType.CONTROLLER_ACK_RECEIVED.value
                        if signals_match
                        else AuditEventType.CONTROLLER_FAILURE.value
                    ),
                    command_id=command_id,
                    details={
                        'actual_signals': confirmed_signals,
                        'requested_signals': cmd.requested_signals,
                        'signals_match': signals_match,
                    },
                    reason=(
                        f"Controller ACK for command {command_id}"
                        + ('' if signals_match else ' — signal mismatch, command marked FAILED')
                    ),
                )

                logger.info(
                    f"ACK received for command {command_id} at {junction_id}. "
                    f"Actual: {confirmed_signals}"
                )

                return {
                    'status': 'accepted',
                    'message': f'ACK processed for command {command_id}',
                    'actual_signals': confirmed_signals,
                }

            elif status == 'NACK' or status == 'FAIL':
                # Command failed
                failure_reason = data.get('reason', 'Controller reported failure')
                self._command_repo.update_command_status(
                    command_id,
                    CommandStatus.FAILED,
                    failure_reason=failure_reason,
                )

                # Mark state as uncertain
                state = self._state_repo.get_snapshot(junction_id)
                self._state_repo.update_state(
                    junction_id=junction_id,
                    expected_version=state.version,
                    controller_health=DeviceHealth.WARNING,
                )

                self._audit_repo.log(
                    junction=junction,
                    event_type=AuditEventType.CONTROLLER_FAILURE.value,
                    command_id=command_id,
                    details={
                        'failure_reason': failure_reason,
                        'requested_signals': cmd.requested_signals,
                    },
                    reason=f"Controller NACK: {failure_reason}",
                )

                logger.warning(
                    f"NACK for command {command_id} at {junction_id}: {failure_reason}"
                )

                return {
                    'status': 'accepted',
                    'message': f'NACK processed for command {command_id}',
                    'failure_reason': failure_reason,
                }

            else:
                raise InvalidCommandError(f"Invalid ACK status: '{status}'")

    def _handle_device_status(self, data: dict) -> Dict:
        """Handle a device status change event (ONLINE/OFFLINE/DEGRADED)."""
        junction_id = data.get('junction_id')
        device_type = data.get('device_type')
        device_status = data.get('status')
        direction = data.get('direction')
        event_id = data.get('event_id')

        if not junction_id:
            raise InvalidCommandError("Missing required field: junction_id")

        try:
            health = DeviceHealth(device_status)
        except (ValueError, KeyError):
            raise InvalidCommandError(
                f"Invalid device status: '{device_status}'. "
                f"Must be one of: {[h.value for h in DeviceHealth]}"
            )

        with transaction.atomic():
            junction = self._junction_repo.get_by_id(junction_id)
            state = self._state_repo.get_snapshot(junction_id)

            previous_health = state.controller_health

            update_kwargs = {
                'junction_id': junction_id,
                'expected_version': state.version,
                'controller_health': health,
            }

            # If going OFFLINE, enter DEGRADED mode
            if health == DeviceHealth.OFFLINE:
                update_kwargs['mode'] = OperatingMode.DEGRADED
                # Set actual signals to UNKNOWN since we can't confirm state
                update_kwargs['actual_signals'] = SignalVector.all_unknown()
                update_kwargs['next_transition_at'] = False  # Stop transitions

            # If coming back ONLINE
            elif health == DeviceHealth.ONLINE and previous_health == DeviceHealth.OFFLINE:
                # Don't automatically return to AUTOMATIC — require explicit action
                # But update health status
                pass

            self._state_repo.update_state(**update_kwargs)

            self._audit_repo.log(
                junction=junction,
                event_type=AuditEventType.DEVICE_STATUS_CHANGED.value,
                direction=direction,
                event_id=event_id,
                previous_state=previous_health.value,
                new_state=health.value,
                details={
                    'device_type': device_type,
                    'direction': direction,
                },
                reason=f"Device {device_type} status: {previous_health.value} → {health.value}",
            )

            logger.info(
                f"Device status change at {junction_id}: "
                f"{device_type} {previous_health.value} → {health.value}"
            )

            return {
                'status': 'accepted',
                'message': f'Device status updated to {health.value}',
                'previous_health': previous_health.value,
                'current_health': health.value,
            }

