"""
Repository layer for the Factory Traffic Management System.

Translates between Django ORM models and domain value objects.
All database operations go through this layer.
"""
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

from traffic.domain.enums import (
    AuditEventType,
    CommandStatus,
    DeviceHealth,
    Direction,
    OperatingMode,
    Phase,
    ProcessingStatus,
    SignalState,
    TransitionState,
    VehicleType,
    VEHICLE_PRIORITY,
    PHASE_DIRECTIONS,
    CONTROLLER_ACK_TIMEOUT,
)
from traffic.domain.models import (
    JunctionStateSnapshot,
    SignalVector,
    WaitingVehicle as DomainWaitingVehicle,
)
from traffic.domain.exceptions import (
    DuplicateEventError,
    JunctionNotFoundError,
    StaleOperationError,
)
from traffic.infrastructure.models import (
    Junction,
    JunctionState,
    WaitingVehicle,
    ProcessedEvent,
    ControllerCommand,
    AuditEntry,
)

logger = logging.getLogger('traffic.repository')


class JunctionRepository:
    """Repository for junction CRUD operations."""

    def get_all(self) -> List[Junction]:
        return list(Junction.objects.all())

    def get_by_id(self, junction_id: str) -> Junction:
        try:
            return Junction.objects.get(junction_id=junction_id)
        except Junction.DoesNotExist:
            raise JunctionNotFoundError(f"Junction '{junction_id}' not found")

    def create(self, junction_id: str, name: str, phase_config: list = None) -> Junction:
        if phase_config is None:
            phase_config = [
                {"phase": "NORTH_SOUTH", "directions": ["NORTH", "SOUTH"]},
                {"phase": "EAST_WEST", "directions": ["EAST", "WEST"]},
            ]
        with transaction.atomic():
            junction = Junction.objects.create(
                junction_id=junction_id,
                name=name,
                phase_config=phase_config,
            )
            # Create initial state with NORTH_SOUTH GREEN
            initial_signals = SignalVector.for_phase(Phase.NORTH_SOUTH).as_dict()
            JunctionState.objects.create(
                junction=junction,
                mode=OperatingMode.AUTOMATIC.value,
                current_phase=Phase.NORTH_SOUTH.value,
                transition_state=TransitionState.STABLE.value,
                desired_signals=initial_signals,
                actual_signals=initial_signals,
                controller_health=DeviceHealth.ONLINE.value,
                next_transition_at=timezone.now() + timedelta(seconds=30),
                phase_started_at=timezone.now(),
                version=1,
            )
        return junction

    def exists(self, junction_id: str) -> bool:
        return Junction.objects.filter(junction_id=junction_id).exists()


class JunctionStateRepository:
    """Repository for junction state operations with optimistic concurrency."""

    def get_snapshot(self, junction_id: str) -> JunctionStateSnapshot:
        """Load a fresh snapshot of the junction state from the database."""
        try:
            junction = Junction.objects.get(junction_id=junction_id)
        except Junction.DoesNotExist:
            raise JunctionNotFoundError(f"Junction '{junction_id}' not found")

        state = junction.state

        # Load queue counts
        queues = {}
        for direction in Direction:
            count = WaitingVehicle.objects.filter(
                junction=junction, direction=direction.value
            ).count()
            queues[direction] = count

        # Load waiting vehicles
        waiting_vehicles = {}
        for direction in Direction:
            vehicles = WaitingVehicle.objects.filter(
                junction=junction, direction=direction.value
            ).order_by('-priority', 'arrived_at')
            waiting_vehicles[direction] = [
                DomainWaitingVehicle(
                    vehicle_id=v.vehicle_id,
                    vehicle_type=VehicleType(v.vehicle_type),
                    direction=Direction(v.direction),
                    arrived_at=v.arrived_at,
                    priority=v.priority,
                )
                for v in vehicles
            ]

        return JunctionStateSnapshot(
            junction_id=junction_id,
            mode=OperatingMode(state.mode),
            current_phase=Phase(state.current_phase),
            transition_state=TransitionState(state.transition_state),
            desired_signals=SignalVector.from_dict(state.desired_signals),
            actual_signals=SignalVector.from_dict(state.actual_signals),
            controller_health=DeviceHealth(state.controller_health),
            active_emergency_direction=(
                Direction(state.active_emergency_direction)
                if state.active_emergency_direction else None
            ),
            next_transition_at=state.next_transition_at,
            version=state.version,
            queues=queues,
            waiting_vehicles=waiting_vehicles,
            phase_started_at=state.phase_started_at,
            manual_direction=(
                Direction(state.manual_direction)
                if state.manual_direction else None
            ),
        )

    def update_state(
        self,
        junction_id: str,
        expected_version: int,
        mode: OperatingMode = None,
        current_phase: Phase = None,
        transition_state: TransitionState = None,
        desired_signals: SignalVector = None,
        actual_signals: SignalVector = None,
        controller_health: DeviceHealth = None,
        active_emergency_direction=None,  # Direction or False to clear
        manual_direction=None,  # Direction or False to clear
        next_transition_at=None,  # datetime or False to clear
        phase_started_at=None,  # datetime or False to clear
    ) -> int:
        """
        Update junction state with optimistic concurrency control.
        Returns the new version number.
        Raises StaleOperationError if the version doesn't match.
        """
        with transaction.atomic():
            # Re-read with lock (best-effort with SQLite)
            try:
                state = JunctionState.objects.select_for_update().get(
                    junction__junction_id=junction_id
                )
            except JunctionState.DoesNotExist:
                raise JunctionNotFoundError(f"Junction state for '{junction_id}' not found")

            if state.version != expected_version:
                raise StaleOperationError(
                    f"State version mismatch for junction '{junction_id}': "
                    f"expected {expected_version}, found {state.version}. "
                    f"Another operation may have modified the state."
                )

            if mode is not None:
                state.mode = mode.value
            if current_phase is not None:
                state.current_phase = current_phase.value
            if transition_state is not None:
                state.transition_state = transition_state.value
            if desired_signals is not None:
                state.desired_signals = desired_signals.as_dict()
            if actual_signals is not None:
                state.actual_signals = actual_signals.as_dict()
            if controller_health is not None:
                state.controller_health = controller_health.value
            if active_emergency_direction is False:
                state.active_emergency_direction = None
            elif active_emergency_direction is not None:
                state.active_emergency_direction = active_emergency_direction.value
            if manual_direction is False:
                state.manual_direction = None
            elif manual_direction is not None:
                state.manual_direction = manual_direction.value
            if next_transition_at is False:
                state.next_transition_at = None
            elif next_transition_at is not None:
                state.next_transition_at = next_transition_at
            if phase_started_at is False:
                state.phase_started_at = None
            elif phase_started_at is not None:
                state.phase_started_at = phase_started_at

            state.version += 1
            state.save()
            return state.version


class EventRepository:
    """Repository for sensor event processing with idempotency."""

    def record_event(
        self,
        event_id: str,
        junction: Junction,
        direction: str,
        event_type: str,
        vehicle_id: str = None,
        vehicle_type: str = None,
        sequence_no: int = None,
        sensor_timestamp: datetime = None,
        status: str = ProcessingStatus.ACCEPTED.value,
        rejection_reason: str = None,
    ) -> Tuple[ProcessedEvent, bool]:
        """
        Record an event. Returns (event, is_new).
        If event_id already exists, returns the existing record with is_new=False.
        Uses database unique constraint for deduplication.
        """
        try:
            with transaction.atomic():
                event = ProcessedEvent.objects.create(
                    event_id=event_id,
                    junction=junction,
                    direction=direction,
                    event_type=event_type,
                    vehicle_id=vehicle_id,
                    vehicle_type=vehicle_type,
                    sequence_no=sequence_no,
                    sensor_timestamp=sensor_timestamp,
                    status=status,
                    rejection_reason=rejection_reason,
                )
                return event, True
        except IntegrityError:
            # Duplicate event_id — return existing
            event = ProcessedEvent.objects.get(event_id=event_id)
            return event, False

    def is_duplicate(self, event_id: str) -> bool:
        return ProcessedEvent.objects.filter(event_id=event_id).exists()

    def claim_event(
        self,
        event_id: str,
        junction: Junction,
        direction: str,
        event_type: str,
        vehicle_id: str = None,
        vehicle_type: str = None,
        sequence_no: int = None,
        sensor_timestamp: datetime = None,
    ) -> Tuple[ProcessedEvent, bool]:
        """
        Atomically claim an event_id before any queue mutation.

        The database unique constraint on event_id guarantees that only one
        transaction can claim a given event_id. The first claimant owns the
        event; any later submission with the same event_id (even one carrying
        a different payload) is treated as a duplicate of the original and is
        never re-applied to the queue. This closes the race between the
        duplicate check and the queue mutation.
        """
        defaults = {
            'junction': junction,
            'direction': direction,
            'event_type': event_type,
            'vehicle_id': vehicle_id,
            'vehicle_type': vehicle_type,
            'sequence_no': sequence_no,
            'sensor_timestamp': sensor_timestamp,
            'status': ProcessingStatus.ACCEPTED.value,
        }
        last_error = None
        for attempt in range(6):
            try:
                with transaction.atomic():
                    event, created = ProcessedEvent.objects.get_or_create(
                        event_id=event_id, defaults=defaults,
                    )
                    return event, created
            except IntegrityError:
                # Lost the create race — another transaction committed this event_id.
                event = ProcessedEvent.objects.get(event_id=event_id)
                return event, False
            except OperationalError as e:
                # SQLite takes a database-level write lock; concurrent writers
                # can hit SQLITE_BUSY. Back off and retry — the unique
                # constraint on event_id still guarantees at-most-once claiming.
                last_error = e
                time.sleep(0.1 * (attempt + 1))

        # Exhausted retries: if another transaction already claimed the event,
        # treat this submission as a duplicate of it; otherwise surface the
        # lock error rather than risking a double application of the event.
        try:
            event = ProcessedEvent.objects.get(event_id=event_id)
            return event, False
        except ProcessedEvent.DoesNotExist:
            if last_error is not None:
                raise last_error
            raise

    def mark_processed(
        self,
        event: ProcessedEvent,
        status: str,
        rejection_reason: str = None,
    ) -> None:
        """Record the final processing status on a claimed event."""
        event.status = status
        if rejection_reason is not None:
            event.rejection_reason = rejection_reason
        event.save()


class QueueRepository:
    """Repository for vehicle queue management."""

    def add_vehicle(
        self,
        junction: Junction,
        direction: str,
        vehicle_id: str,
        vehicle_type: str,
        arrived_at: datetime,
        event_id: str,
    ) -> Tuple[WaitingVehicle, bool]:
        """
        Add a vehicle to the queue. Returns (vehicle, is_new).
        If vehicle_id already exists at this junction, returns existing with is_new=False.
        """
        priority = VEHICLE_PRIORITY.get(VehicleType(vehicle_type), 10)
        last_error = None
        for attempt in range(6):
            try:
                with transaction.atomic():
                    vehicle = WaitingVehicle.objects.create(
                        junction=junction,
                        direction=direction,
                        vehicle_id=vehicle_id,
                        vehicle_type=vehicle_type,
                        priority=priority,
                        arrived_at=arrived_at,
                        event_id=event_id,
                    )
                    return vehicle, True
            except IntegrityError:
                vehicle = WaitingVehicle.objects.get(
                    junction=junction, vehicle_id=vehicle_id
                )
                return vehicle, False
            except OperationalError as e:
                last_error = e
                time.sleep(0.1 * (attempt + 1))

        # Exhausted retries: another writer may have created the vehicle
        # in the meantime. Return it as existing rather than double-apply.
        try:
            vehicle = WaitingVehicle.objects.get(
                junction=junction, vehicle_id=vehicle_id
            )
            return vehicle, False
        except WaitingVehicle.DoesNotExist:
            if last_error is not None:
                raise last_error
            raise

    def remove_vehicle(self, junction: Junction, vehicle_id: str) -> bool:
        """Remove a vehicle from the queue. Returns True if removed."""
        deleted, _ = WaitingVehicle.objects.filter(
            junction=junction, vehicle_id=vehicle_id
        ).delete()
        return deleted > 0

    def get_queue_counts(self, junction: Junction) -> Dict[str, int]:
        """Get queue counts by direction."""
        counts = {}
        for direction in Direction:
            counts[direction.value] = WaitingVehicle.objects.filter(
                junction=junction, direction=direction.value
            ).count()
        return counts

    def get_vehicles_in_direction(
        self, junction: Junction, direction: str
    ) -> List[WaitingVehicle]:
        return list(
            WaitingVehicle.objects.filter(
                junction=junction, direction=direction
            ).order_by('-priority', 'arrived_at')
        )

    def get_vehicle_by_id(
        self, junction: Junction, vehicle_id: str
    ) -> Optional[WaitingVehicle]:
        """Return the WaitingVehicle ORM row for a vehicle, or None."""
        try:
            return WaitingVehicle.objects.get(junction=junction, vehicle_id=vehicle_id)
        except WaitingVehicle.DoesNotExist:
            return None

    def clear_vehicles_in_phase(self, junction: Junction, phase: Phase) -> int:
        """Clear all vehicles in directions belonging to a phase."""
        directions = [d.value for d in PHASE_DIRECTIONS[phase]]
        deleted, _ = WaitingVehicle.objects.filter(
            junction=junction, direction__in=directions
        ).delete()
        return deleted


class CommandRepository:
    """Repository for controller command management."""

    def create_command(
        self,
        junction: Junction,
        requested_signals: dict,
        direction: str = None,
    ) -> ControllerCommand:
        """Create a new controller command with a unique command_id."""
        command_id = f"cmd-{uuid.uuid4().hex[:8]}"
        return ControllerCommand.objects.create(
            command_id=command_id,
            junction=junction,
            direction=direction,
            requested_signals=requested_signals,
            status=CommandStatus.PENDING.value,
            timeout_at=timezone.now() + timedelta(seconds=CONTROLLER_ACK_TIMEOUT),
        )

    def get_by_command_id(self, command_id: str) -> Optional[ControllerCommand]:
        try:
            return ControllerCommand.objects.get(command_id=command_id)
        except ControllerCommand.DoesNotExist:
            return None

    def get_pending_commands(self, junction: Junction) -> List[ControllerCommand]:
        return list(
            ControllerCommand.objects.filter(
                junction=junction,
                status__in=[CommandStatus.PENDING.value, CommandStatus.SENT.value],
            ).order_by('created_at')
        )

    def get_timed_out_commands(self) -> List[ControllerCommand]:
        """Get commands that have exceeded their timeout."""
        now = timezone.now()
        return list(
            ControllerCommand.objects.filter(
                status__in=[CommandStatus.PENDING.value, CommandStatus.SENT.value],
                timeout_at__lte=now,
            )
        )

    def update_command_status(
        self,
        command_id: str,
        status: CommandStatus,
        actual_signals: dict = None,
        failure_reason: str = None,
    ) -> Optional[ControllerCommand]:
        """Update command status."""
        try:
            cmd = ControllerCommand.objects.get(command_id=command_id)
        except ControllerCommand.DoesNotExist:
            return None

        cmd.status = status.value
        if status == CommandStatus.ACKNOWLEDGED:
            cmd.acked_at = timezone.now()
            cmd.actual_signals_on_ack = actual_signals
        if failure_reason:
            cmd.failure_reason = failure_reason
        cmd.save()
        return cmd

    def supersede_pending_commands(self, junction: Junction) -> int:
        """Mark all pending commands for a junction as superseded."""
        updated = ControllerCommand.objects.filter(
            junction=junction,
            status__in=[CommandStatus.PENDING.value, CommandStatus.SENT.value],
        ).update(status=CommandStatus.SUPERSEDED.value)
        return updated


class AuditRepository:
    """Repository for the append-only audit trail."""

    def log(
        self,
        junction: Junction,
        event_type: str,
        direction: str = None,
        previous_state: str = None,
        new_state: str = None,
        event_id: str = None,
        command_id: str = None,
        details: dict = None,
        reason: str = None,
    ) -> AuditEntry:
        """Append an audit entry."""
        return AuditEntry.objects.create(
            junction=junction,
            event_type=event_type,
            direction=direction,
            previous_state=previous_state,
            new_state=new_state,
            event_id=event_id,
            command_id=command_id,
            details=details or {},
            reason=reason,
        )

    def get_history(
        self, junction: Junction, limit: int = 50, event_type: str = None
    ) -> List[AuditEntry]:
        qs = AuditEntry.objects.filter(junction=junction)
        if event_type:
            qs = qs.filter(event_type=event_type)
        return list(qs.order_by('-timestamp')[:limit])

