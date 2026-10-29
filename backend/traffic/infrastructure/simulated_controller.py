"""
Simulated controller service for development and testing.

Automatically acknowledges pending controller commands after a brief delay.
Clearly distinguished from real physical-controller confirmation via
is_simulated=True on all commands.

In production, this would be replaced by an MQTT adapter that communicates
with real physical controllers.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from traffic.domain.enums import (
    AuditEventType,
    CommandStatus,
    DeviceHealth,
)
from traffic.domain.models import SignalVector
from traffic.infrastructure.models import ControllerCommand, Junction
from traffic.infrastructure.repositories import (
    AuditRepository,
    CommandRepository,
    JunctionStateRepository,
)

logger = logging.getLogger('traffic.simulated_controller')

# Simulated ACK delay — commands are ACK'd after this many seconds
SIMULATED_ACK_DELAY_SECONDS = 0.5


class SimulatedControllerService:
    """
    Simulated physical controller that automatically ACKs commands.
    
    This is a REST-based simulation for the assessment.
    A real controller would use MQTT or another protocol.
    
    The simulator:
    - Picks up PENDING commands that are older than the ACK delay
    - Sets their status to ACKNOWLEDGED
    - Updates the junction's actual_signals to match the requested signals
    - Marks all commands as is_simulated=True
    
    IMPORTANT: This simulated ACK is clearly distinguished from real
    physical controller confirmation. The is_simulated flag is always True.
    """

    def __init__(self):
        self._state_repo = JunctionStateRepository()
        self._command_repo = CommandRepository()
        self._audit_repo = AuditRepository()

    def process_pending_commands(self) -> int:
        """
        Process pending commands by simulating controller ACKs.
        Returns the number of commands ACK'd.
        """
        now = timezone.now()
        ack_threshold = now - timedelta(seconds=SIMULATED_ACK_DELAY_SECONDS)

        # Find pending commands that are old enough to ACK
        pending_commands = ControllerCommand.objects.filter(
            status__in=[CommandStatus.PENDING.value, CommandStatus.SENT.value],
            created_at__lte=ack_threshold,
            is_simulated=True,
        ).select_related('junction')

        acked = 0
        for cmd in pending_commands:
            try:
                self._simulate_ack(cmd)
                acked += 1
            except Exception as e:
                logger.error(
                    f"Failed to simulate ACK for {cmd.command_id}: {e}",
                    exc_info=True,
                )

        return acked

    def _simulate_ack(self, cmd: ControllerCommand):
        """Simulate a controller ACK for a single command."""
        junction = cmd.junction

        with transaction.atomic():
            # Check junction health — don't ACK if controller is OFFLINE
            state = self._state_repo.get_snapshot(junction.junction_id)
            if state.controller_health == DeviceHealth.OFFLINE:
                logger.info(
                    f"Skipping simulated ACK for {cmd.command_id}: "
                    f"controller is OFFLINE"
                )
                return

            # Update command status
            cmd.status = CommandStatus.ACKNOWLEDGED.value
            cmd.acked_at = timezone.now()
            cmd.actual_signals_on_ack = cmd.requested_signals
            cmd.save()

            # Update actual signals to match requested
            actual_signals = SignalVector.from_dict(cmd.requested_signals)
            self._state_repo.update_state(
                junction_id=junction.junction_id,
                expected_version=state.version,
                actual_signals=actual_signals,
                controller_health=DeviceHealth.ONLINE,
            )

            self._audit_repo.log(
                junction=junction,
                event_type=AuditEventType.CONTROLLER_ACK_RECEIVED.value,
                command_id=cmd.command_id,
                details={
                    'actual_signals': cmd.requested_signals,
                    'simulated': True,
                },
                reason=f"Simulated ACK for command {cmd.command_id}",
            )

            logger.debug(
                f"Simulated ACK for {cmd.command_id} at {junction.junction_id}"
            )

