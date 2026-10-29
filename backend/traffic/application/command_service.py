"""
Command service for manual control and emergency handling.

Processes manual GREEN requests, return-to-automatic commands,
and emergency preemption through the domain state machine.
"""
import logging
from typing import Dict

from django.db import transaction
from django.utils import timezone

from traffic.domain.clock import Clock, SystemClock
from traffic.domain.enums import (
    AuditEventType,
    CommandType,
    DeviceHealth,
    Direction,
    OperatingMode,
    Phase,
    TransitionState,
)
from traffic.domain.exceptions import InvalidCommandError
from traffic.domain.models import TransitionResult
from traffic.domain.state_machine import TrafficStateMachine
from traffic.domain.safety import get_phase_for_direction
from traffic.infrastructure.repositories import (
    AuditRepository,
    CommandRepository,
    JunctionRepository,
    JunctionStateRepository,
)

logger = logging.getLogger('traffic.command_service')


class CommandService:
    """
    Application service for processing control commands.
    
    Responsibilities:
    - Validate commands
    - Execute through domain state machine
    - Persist state changes
    - Create controller commands
    - Log audit entries
    """

    def __init__(self, clock: Clock = None):
        self._clock = clock or SystemClock()
        self._state_machine = TrafficStateMachine(self._clock)
        self._junction_repo = JunctionRepository()
        self._state_repo = JunctionStateRepository()
        self._command_repo = CommandRepository()
        self._audit_repo = AuditRepository()

    def process_command(self, junction_id: str, data: dict) -> Dict:
        """
        Process a manual control command.
        
        Returns a result dict with status and details.
        """
        command_type_str = data.get('command')
        direction_str = data.get('direction')

        if not command_type_str:
            raise InvalidCommandError("Missing required field: command")

        try:
            command_type = CommandType(command_type_str)
        except ValueError:
            raise InvalidCommandError(
                f"Invalid command: '{command_type_str}'. "
                f"Must be one of: {[c.value for c in CommandType]}"
            )

        if command_type == CommandType.MANUAL_GREEN_REQUEST:
            return self._handle_manual_green(junction_id, direction_str)
        elif command_type == CommandType.RETURN_TO_AUTOMATIC:
            return self._handle_return_to_automatic(junction_id)

    def _handle_manual_green(self, junction_id: str, direction_str: str) -> Dict:
        """Handle a manual GREEN request."""
        if not direction_str:
            raise InvalidCommandError(
                "Missing required field: direction for MANUAL_GREEN_REQUEST"
            )

        try:
            direction = Direction(direction_str)
        except ValueError:
            raise InvalidCommandError(
                f"Invalid direction: '{direction_str}'. "
                f"Must be one of: {[d.value for d in Direction]}"
            )

        with transaction.atomic():
            state = self._state_repo.get_snapshot(junction_id)
            junction = self._junction_repo.get_by_id(junction_id)

            # Use domain state machine for validation and transition
            result = self._state_machine.initiate_manual_green(state, direction)

            # Apply the transition result
            self._apply_transition(junction, state, result, direction)

            # Audit
            self._audit_repo.log(
                junction=junction,
                event_type=AuditEventType.MANUAL_OVERRIDE.value,
                direction=direction_str,
                previous_state=state.mode.value,
                new_state=OperatingMode.MANUAL.value,
                details={
                    'requested_direction': direction_str,
                    'transition_state': result.new_transition_state.value,
                    'reason': result.reason,
                },
                reason=result.reason,
            )

            logger.info(
                f"Manual GREEN requested for {junction_id}/{direction_str}: "
                f"{result.reason}"
            )

            return {
                'status': 'accepted',
                'command': CommandType.MANUAL_GREEN_REQUEST.value,
                'direction': direction_str,
                'message': result.reason,
                'transition_state': result.new_transition_state.value,
            }

    def _handle_return_to_automatic(self, junction_id: str) -> Dict:
        """Handle return to automatic mode."""
        with transaction.atomic():
            state = self._state_repo.get_snapshot(junction_id)
            junction = self._junction_repo.get_by_id(junction_id)

            result = self._state_machine.return_to_automatic(state)

            # Apply the transition result
            self._apply_transition(junction, state, result)

            # Clear manual direction
            self._state_repo.update_state(
                junction_id=junction_id,
                expected_version=state.version + 1,  # Version was already bumped
                manual_direction=False,
                active_emergency_direction=False,
            )

            # Audit
            self._audit_repo.log(
                junction=junction,
                event_type=AuditEventType.RETURN_TO_AUTOMATIC.value,
                previous_state=state.mode.value,
                new_state=OperatingMode.AUTOMATIC.value,
                details={'reason': result.reason},
                reason=result.reason,
            )

            logger.info(f"Returned {junction_id} to AUTOMATIC: {result.reason}")

            return {
                'status': 'accepted',
                'command': CommandType.RETURN_TO_AUTOMATIC.value,
                'message': result.reason,
                'mode': OperatingMode.AUTOMATIC.value,
            }

    def handle_emergency(
        self,
        junction_id: str,
        direction: Direction,
        vehicle_id: str,
        event_id: str,
    ) -> Dict:
        """Handle an emergency vehicle arrival."""
        with transaction.atomic():
            state = self._state_repo.get_snapshot(junction_id)
            junction = self._junction_repo.get_by_id(junction_id)

            result = self._state_machine.initiate_emergency_preemption(
                state, direction
            )

            if result is None:
                return {
                    'status': 'no_action',
                    'message': 'No transition needed for emergency',
                }

            # Apply transition
            self._apply_transition(junction, state, result, direction)

            # Set emergency direction
            self._state_repo.update_state(
                junction_id=junction_id,
                expected_version=state.version + 1,
                active_emergency_direction=direction,
            )

            # Audit
            self._audit_repo.log(
                junction=junction,
                event_type=AuditEventType.EMERGENCY_DETECTED.value,
                direction=direction.value,
                event_id=event_id,
                details={
                    'vehicle_id': vehicle_id,
                    'transition_state': result.new_transition_state.value,
                    'reason': result.reason,
                },
                reason=result.reason,
            )

            logger.info(
                f"Emergency preemption at {junction_id}/{direction.value}: "
                f"{result.reason}"
            )

            return {
                'status': 'accepted',
                'message': result.reason,
                'mode': OperatingMode.EMERGENCY.value,
            }

    def _apply_transition(
        self,
        junction,
        state,
        result: TransitionResult,
        direction: Direction = None,
    ):
        """Apply a TransitionResult to the persisted state."""
        update_kwargs = {
            'junction_id': junction.junction_id,
            'expected_version': state.version,
            'transition_state': result.new_transition_state,
            'desired_signals': result.new_desired_signals,
        }

        if result.new_phase is not None:
            update_kwargs['current_phase'] = result.new_phase
        if result.new_mode is not None:
            update_kwargs['mode'] = result.new_mode
        if result.next_transition_at is not None:
            update_kwargs['next_transition_at'] = result.next_transition_at
        elif result.next_transition_at is None and result.new_mode == OperatingMode.MANUAL:
            update_kwargs['next_transition_at'] = False  # Clear for manual mode

        if direction is not None and result.new_mode == OperatingMode.MANUAL:
            update_kwargs['manual_direction'] = direction

        if result.phase_changed:
            update_kwargs['phase_started_at'] = self._clock.now()

        self._state_repo.update_state(**update_kwargs)

        # Create controller command if signals changed
        if result.new_desired_signals != state.desired_signals:
            self._command_repo.supersede_pending_commands(junction)
            cmd = self._command_repo.create_command(
                junction=junction,
                requested_signals=result.new_desired_signals.as_dict(),
            )
            self._audit_repo.log(
                junction=junction,
                event_type=AuditEventType.CONTROLLER_COMMAND_SENT.value,
                command_id=cmd.command_id,
                details={
                    'requested_signals': result.new_desired_signals.as_dict(),
                    'reason': result.reason,
                },
                reason=f"Controller command sent: {result.reason}",
            )

