"""
Transition service for non-blocking transition scheduling.

Processes due transitions by reading persisted state and applying
the domain state machine's decisions. Designed to be called
periodically by a management command (transition worker).
"""
import logging
from typing import List, Optional

from django.db import transaction
from django.utils import timezone

from traffic.domain.clock import Clock, SystemClock
from traffic.domain.enums import (
    AuditEventType,
    CommandStatus,
    DeviceHealth,
    OperatingMode,
    TransitionState,
)
from traffic.domain.models import TransitionResult
from traffic.domain.state_machine import TrafficStateMachine
from traffic.domain.scheduling import TrafficScheduler
from traffic.domain.safety import get_opposing_phase
from traffic.infrastructure.models import Junction, JunctionState
from traffic.infrastructure.repositories import (
    AuditRepository,
    CommandRepository,
    JunctionStateRepository,
)

logger = logging.getLogger('traffic.transition_service')


class TransitionService:
    """
    Application service for processing due transitions.
    
    Called periodically by the transition worker.
    Re-reads state from the database before making decisions.
    """

    def __init__(self, clock: Clock = None):
        self._clock = clock or SystemClock()
        self._state_machine = TrafficStateMachine(self._clock)
        self._scheduler = TrafficScheduler(self._clock)
        self._state_repo = JunctionStateRepository()
        self._command_repo = CommandRepository()
        self._audit_repo = AuditRepository()

    def process_all_due_transitions(self) -> int:
        """
        Process all due transitions across all junctions.
        Returns the number of transitions processed.
        """
        processed = 0
        now = timezone.now()

        # Find junctions with due transitions
        due_states = JunctionState.objects.filter(
            next_transition_at__lte=now,
            mode__in=[
                OperatingMode.AUTOMATIC.value,
                OperatingMode.MANUAL.value,
                OperatingMode.EMERGENCY.value,
            ],
        ).select_related('junction')

        for js in due_states:
            try:
                if self._process_junction_transition(js.junction.junction_id):
                    processed += 1
            except Exception as e:
                logger.error(
                    f"Error processing transition for {js.junction.junction_id}: {e}",
                    exc_info=True,
                )

        return processed

    def _process_junction_transition(self, junction_id: str) -> bool:
        """
        Process a single junction's due transition.
        Returns True if a transition was applied.
        """
        with transaction.atomic():
            # Fresh read from database
            state = self._state_repo.get_snapshot(junction_id)
            junction_obj = Junction.objects.get(junction_id=junction_id)

            # For AUTOMATIC mode at STABLE state, run scheduler first
            if (
                state.mode == OperatingMode.AUTOMATIC
                and state.transition_state == TransitionState.STABLE
            ):
                decision = self._scheduler.evaluate(state)
                if not decision.should_switch:
                    # Stay on current phase, just reschedule
                    from datetime import timedelta
                    from traffic.domain.enums import DEFAULT_GREEN_DURATION
                    self._state_repo.update_state(
                        junction_id=junction_id,
                        expected_version=state.version,
                        next_transition_at=self._clock.now() + timedelta(
                            seconds=DEFAULT_GREEN_DURATION
                        ),
                    )
                    self._audit_repo.log(
                        junction=junction_obj,
                        event_type=AuditEventType.SCHEDULING_DECISION.value,
                        details={
                            'decision': 'stay',
                            'scores': {
                                k.value: v for k, v in decision.scores.items()
                            },
                            'reason': decision.reason,
                        },
                        reason=decision.reason,
                    )
                    return True

            # Use state machine to determine transition
            result = self._state_machine.process_due_transition(state)

            if result is None:
                return False

            # Apply the transition
            update_kwargs = {
                'junction_id': junction_id,
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
            if result.phase_changed:
                update_kwargs['phase_started_at'] = self._clock.now()

            # If going to GREEN after emergency, clear emergency direction
            if (
                result.new_transition_state == TransitionState.STABLE
                and state.mode == OperatingMode.EMERGENCY
            ):
                # Emergency is resolved once the phase is active
                pass  # Emergency stays until explicitly cleared

            self._state_repo.update_state(**update_kwargs)

            # Create controller command for signal changes
            if result.new_desired_signals != state.desired_signals:
                self._command_repo.supersede_pending_commands(junction_obj)
                cmd = self._command_repo.create_command(
                    junction=junction_obj,
                    requested_signals=result.new_desired_signals.as_dict(),
                )
                self._audit_repo.log(
                    junction=junction_obj,
                    event_type=AuditEventType.CONTROLLER_COMMAND_SENT.value,
                    command_id=cmd.command_id,
                    details={
                        'requested_signals': result.new_desired_signals.as_dict(),
                    },
                    reason=f"Controller command: {result.reason}",
                )

            # Audit the transition
            self._audit_repo.log(
                junction=junction_obj,
                event_type=AuditEventType.TRANSITION_STATE_CHANGED.value,
                previous_state=state.transition_state.value,
                new_state=result.new_transition_state.value,
                details={
                    'phase': result.new_phase.value if result.new_phase else None,
                    'desired_signals': result.new_desired_signals.as_dict(),
                    'reason': result.reason,
                    'phase_changed': result.phase_changed,
                },
                reason=result.reason,
            )

            logger.info(
                f"Transition at {junction_id}: "
                f"{state.transition_state.value} → {result.new_transition_state.value} "
                f"({result.reason})"
            )

            return True

    def check_command_timeouts(self) -> int:
        """Check for timed-out controller commands."""
        timed_out = self._command_repo.get_timed_out_commands()
        count = 0

        for cmd in timed_out:
            try:
                with transaction.atomic():
                    self._command_repo.update_command_status(
                        cmd.command_id,
                        CommandStatus.TIMED_OUT,
                        failure_reason="ACK timeout exceeded",
                    )

                    self._audit_repo.log(
                        junction=cmd.junction,
                        event_type=AuditEventType.CONTROLLER_TIMEOUT.value,
                        command_id=cmd.command_id,
                        details={
                            'requested_signals': cmd.requested_signals,
                            'timeout_at': cmd.timeout_at.isoformat() if cmd.timeout_at else None,
                        },
                        reason=f"Controller command {cmd.command_id} timed out",
                    )

                    # Enter DEGRADED if too many timeouts
                    pending = self._command_repo.get_pending_commands(cmd.junction)
                    if not pending:
                        # No more pending commands — consider entering WARNING
                        state = self._state_repo.get_snapshot(cmd.junction.junction_id)
                        if state.controller_health == DeviceHealth.ONLINE:
                            self._state_repo.update_state(
                                junction_id=cmd.junction.junction_id,
                                expected_version=state.version,
                                controller_health=DeviceHealth.WARNING,
                            )

                    count += 1
                    logger.warning(
                        f"Command {cmd.command_id} timed out at {cmd.junction.junction_id}"
                    )
            except Exception as e:
                logger.error(f"Error processing timeout for {cmd.command_id}: {e}")

        return count

    def clear_stale_emergencies(self) -> int:
        """
        Clear emergency modes whose emergency vehicle has not been cleared
        within the stale-emergency timeout.

        Implements the documented assumption: a 300-second timeout
        automatically clears stale emergencies when sensor clearance packets
        are dropped and the emergency vehicle never reports VEHICLE_CLEARED.
        Only affects junctions in EMERGENCY mode with an active emergency
        direction and an un-cleared emergency vehicle still waiting past the
        timeout.
        """
        from datetime import timedelta

        from django.utils import timezone

        from traffic.domain.enums import (
            DEFAULT_GREEN_DURATION,
            EMERGENCY_TIMEOUT,
            VehicleType,
        )
        from traffic.infrastructure.models import WaitingVehicle

        cleared = 0
        now = timezone.now()
        cutoff = now - timedelta(seconds=EMERGENCY_TIMEOUT)

        emergency_states = JunctionState.objects.filter(
            mode=OperatingMode.EMERGENCY.value,
            active_emergency_direction__isnull=False,
        ).select_related('junction')

        for state in emergency_states:
            still_waiting = WaitingVehicle.objects.filter(
                junction=state.junction,
                direction=state.active_emergency_direction,
                vehicle_type=VehicleType.EMERGENCY.value,
                arrived_at__lt=cutoff,
            ).exists()

            if not still_waiting:
                continue

            try:
                with transaction.atomic():
                    fresh = self._state_repo.get_snapshot(state.junction.junction_id)
                    direction = fresh.active_emergency_direction
                    self._state_repo.update_state(
                        junction_id=state.junction.junction_id,
                        expected_version=fresh.version,
                        mode=OperatingMode.AUTOMATIC,
                        active_emergency_direction=False,
                        next_transition_at=now + timedelta(
                            seconds=DEFAULT_GREEN_DURATION
                        ),
                    )
                    self._audit_repo.log(
                        junction=state.junction,
                        event_type=AuditEventType.EMERGENCY_CLEARED.value,
                        direction=direction.value if direction else None,
                        details={
                            'reason': 'stale emergency timeout',
                            'timeout_seconds': EMERGENCY_TIMEOUT,
                        },
                        reason="Stale emergency timeout; returned to AUTOMATIC",
                    )
                    cleared += 1
                    logger.warning(
                        f"Cleared stale emergency at {state.junction.junction_id} "
                        f"direction {state.active_emergency_direction}"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to clear stale emergency at "
                    f"{state.junction.junction_id}: {e}"
                )

        return cleared

