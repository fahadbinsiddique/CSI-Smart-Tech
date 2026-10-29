"""
Recovery service for handling backend restarts.

Conservative recovery policy:
- If controller state is unknown → DEGRADED + ALL_RED
- If was in mid-transition → ALL_RED, re-evaluate
- Never blindly advance to GREEN after restart
- Require explicit confirmation before resuming GREEN
"""
import logging

from django.utils import timezone

from traffic.domain.clock import Clock, SystemClock
from traffic.domain.enums import (
    AuditEventType,
    DeviceHealth,
    OperatingMode,
    TransitionState,
)
from traffic.domain.state_machine import TrafficStateMachine
from traffic.infrastructure.models import Junction
from traffic.infrastructure.repositories import (
    AuditRepository,
    JunctionStateRepository,
)

logger = logging.getLogger('traffic.recovery_service')


class RecoveryService:
    """
    Application service for backend restart recovery.
    
    Called on startup to ensure all junctions are in a safe state.
    """

    def __init__(self, clock: Clock = None):
        self._clock = clock or SystemClock()
        self._state_machine = TrafficStateMachine(self._clock)
        self._state_repo = JunctionStateRepository()
        self._audit_repo = AuditRepository()

    def recover_all_junctions(self) -> int:
        """
        Run recovery for all junctions.
        Returns the number of junctions that needed recovery.
        """
        recovered = 0
        for junction in Junction.objects.all():
            try:
                if self._recover_junction(junction):
                    recovered += 1
            except Exception as e:
                logger.error(
                    f"Recovery failed for junction {junction.junction_id}: {e}",
                    exc_info=True,
                )
        return recovered

    def _recover_junction(self, junction) -> bool:
        """
        Recover a single junction. Returns True if recovery was applied.
        """
        state = self._state_repo.get_snapshot(junction.junction_id)

        result = self._state_machine.compute_recovery_state(state)

        # Check if recovery actually changes anything
        needs_recovery = (
            result.new_transition_state != state.transition_state
            or result.new_desired_signals != state.desired_signals
            or (result.new_mode and result.new_mode != state.mode)
        )

        if not needs_recovery:
            logger.info(
                f"Junction {junction.junction_id} is in safe state, "
                f"no recovery needed"
            )
            return False

        # Apply recovery
        self._state_repo.update_state(
            junction_id=junction.junction_id,
            expected_version=state.version,
            mode=result.new_mode,
            transition_state=result.new_transition_state,
            desired_signals=result.new_desired_signals,
            next_transition_at=result.next_transition_at or False,
            phase_started_at=False,
        )

        self._audit_repo.log(
            junction=junction,
            event_type=AuditEventType.RECOVERY_EVENT.value,
            previous_state=state.transition_state.value,
            new_state=result.new_transition_state.value,
            details={
                'previous_mode': state.mode.value,
                'new_mode': result.new_mode.value if result.new_mode else None,
                'desired_signals': result.new_desired_signals.as_dict(),
                'reason': result.reason,
            },
            reason=result.reason,
        )

        logger.info(
            f"Recovery applied to {junction.junction_id}: {result.reason}"
        )

        return True

