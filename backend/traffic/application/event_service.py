"""
Event processing service for sensor events.

Handles vehicle arrival, clearance, duplicate detection, and queue management.
Ensures idempotent processing through event_id deduplication.
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from django.db import OperationalError, transaction
from django.utils import timezone

from traffic.domain.enums import (
    AuditEventType,
    Direction,
    EventType,
    OperatingMode,
    Phase,
    ProcessingStatus,
    TransitionState,
    VehicleType,
    VEHICLE_PRIORITY,
    DEFAULT_GREEN_DURATION,
)
from traffic.domain.exceptions import (
    DuplicateEventError,
    InvalidEventError,
    JunctionNotFoundError,
)
from traffic.domain.clock import Clock, SystemClock
from traffic.infrastructure.repositories import (
    AuditRepository,
    EventRepository,
    JunctionRepository,
    JunctionStateRepository,
    QueueRepository,
)

logger = logging.getLogger('traffic.event_service')


class EventService:
    """
    Application service for processing sensor events.
    
    Responsibilities:
    - Validate incoming events
    - Deduplicate by event_id
    - Manage vehicle queues
    - Log audit entries
    - Trigger scheduling evaluation if needed
    """

    def __init__(self, clock: Clock = None):
        self._clock = clock or SystemClock()
        self._junction_repo = JunctionRepository()
        self._state_repo = JunctionStateRepository()
        self._event_repo = EventRepository()
        self._queue_repo = QueueRepository()
        self._audit_repo = AuditRepository()

    def process_sensor_event(self, data: dict) -> Dict:
        """
        Process a sensor event.
        
        Returns a result dict with status and details.
        Raises InvalidEventError for validation failures.
        """
        # Validate required fields
        event_id = data.get('event_id')
        junction_id = data.get('junction_id')
        direction_str = data.get('direction')
        event_type_str = data.get('event_type')
        vehicle_id = data.get('vehicle_id')
        vehicle_type_str = data.get('vehicle_type')
        sequence_no = data.get('sequence_no')
        timestamp_str = data.get('timestamp')

        if not event_id:
            raise InvalidEventError("Missing required field: event_id")
        if not junction_id:
            raise InvalidEventError("Missing required field: junction_id")
        if not event_type_str:
            raise InvalidEventError("Missing required field: event_type")

        # Validate event type
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            raise InvalidEventError(
                f"Invalid event_type: '{event_type_str}'. "
                f"Must be one of: {[e.value for e in EventType]}"
            )

        # Validate direction
        if not direction_str:
            raise InvalidEventError("Missing required field: direction")
        try:
            direction = Direction(direction_str)
        except ValueError:
            raise InvalidEventError(
                f"Invalid direction: '{direction_str}'. "
                f"Must be one of: {[d.value for d in Direction]}"
            )

        # Validate junction exists
        try:
            junction = self._junction_repo.get_by_id(junction_id)
        except JunctionNotFoundError:
            raise InvalidEventError(f"Unknown junction: '{junction_id}'")

        # Validate vehicle type for arrivals
        if event_type == EventType.VEHICLE_ARRIVED:
            if not vehicle_id:
                raise InvalidEventError("Missing required field: vehicle_id for VEHICLE_ARRIVED")
            if not vehicle_type_str:
                raise InvalidEventError("Missing required field: vehicle_type for VEHICLE_ARRIVED")
            try:
                vehicle_type = VehicleType(vehicle_type_str)
            except ValueError:
                raise InvalidEventError(
                    f"Invalid vehicle_type: '{vehicle_type_str}'. "
                    f"Must be one of: {[v.value for v in VehicleType]}"
                )
        elif event_type == EventType.VEHICLE_CLEARED:
            if not vehicle_id:
                raise InvalidEventError("Missing required field: vehicle_id for VEHICLE_CLEARED")
            vehicle_type = None

        # Parse sensor timestamp
        sensor_timestamp = None
        if timestamp_str:
            try:
                sensor_timestamp = datetime.fromisoformat(
                    timestamp_str.replace('Z', '+00:00')
                )
            except (ValueError, TypeError):
                raise InvalidEventError(f"Invalid timestamp format: '{timestamp_str}'")

        received_at = self._clock.now()

        last_error = None
        for attempt in range(3):
            # Process atomically. The event_id is claimed BEFORE any queue
                # mutation so that concurrent duplicate submissions — including
                # ones carrying a different payload — can never apply the queue
                # mutation twice. The first claimant owns the event; every later
                # submission with the same event_id is a duplicate of the
                # original. Because claiming is idempotent, a transaction that
                # loses a SQLite write lock can safely be retried: the retry
                # will observe the winner's claimed event and return DUPLICATE
                # without touching the queue.
                try:
                    with transaction.atomic():
                        event, is_new = self._event_repo.claim_event(
                            event_id=event_id,
                            junction=junction,
                            direction=direction_str,
                            event_type=event_type_str,
                            vehicle_id=vehicle_id,
                            vehicle_type=vehicle_type_str,
                            sequence_no=sequence_no,
                            sensor_timestamp=sensor_timestamp,
                        )

                        if not is_new:
                            # Already processed under this event_id. Return the
                            # outcome of the original processing and never
                            # re-apply or mutate the queue.
                            self._audit_repo.log(
                                junction=junction,
                                event_type=AuditEventType.DUPLICATE_EVENT.value,
                                direction=direction_str,
                                event_id=event_id,
                                details={
                                    'vehicle_id': vehicle_id,
                                    'event_type': event_type_str,
                                    'original_status': event.status,
                                },
                                reason=f"Duplicate event_id '{event_id}' already processed",
                            )
                            logger.info(f"Duplicate event: {event_id}")
                            return {
                                'status': ProcessingStatus.DUPLICATE.value,
                                'event_id': event_id,
                                'message': 'Event already processed',
                            }

                        # Process based on event type
                        if event_type == EventType.VEHICLE_ARRIVED:
                            result = self._process_arrival(
                                junction, direction, vehicle_id, vehicle_type,
                                sensor_timestamp or received_at, event_id, sequence_no
                            )
                        else:
                            result = self._process_clearance(
                                junction, direction, vehicle_id,
                                sensor_timestamp or received_at, event_id, sequence_no
                            )

                        # Record the final processing status on the claimed event
                        self._event_repo.mark_processed(
                            event,
                            result['status'],
                            result.get('rejection_reason'),
                        )

                        return result
                except OperationalError as exc:
                    # SQLite serializes writers; under concurrent writer
                    # contention we may briefly hit "database is locked".
                    # Retrying is safe: claiming is idempotent, so the retry
                    # observes the winner's claimed event and returns DUPLICATE
                    # without touching the queue.
                    last_error = exc
                    time.sleep(0.1 * (attempt + 1))
        raise last_error

    def _process_arrival(
        self,
        junction,
        direction: Direction,
        vehicle_id: str,
        vehicle_type: VehicleType,
        arrived_at: datetime,
        event_id: str,
        sequence_no: int = None,
    ) -> Dict:
        """Process a vehicle arrival event."""
        vehicle, is_new = self._queue_repo.add_vehicle(
            junction=junction,
            direction=direction.value,
            vehicle_id=vehicle_id,
            vehicle_type=vehicle_type.value,
            arrived_at=arrived_at,
            event_id=event_id,
        )

        if not is_new:
            logger.info(
                f"Vehicle {vehicle_id} already in queue at {direction.value}"
            )
            return {
                'status': ProcessingStatus.DUPLICATE.value,
                'event_id': event_id,
                'message': f'Vehicle {vehicle_id} already in queue',
            }

        # Log audit entry
        self._audit_repo.log(
            junction=junction,
            event_type=AuditEventType.VEHICLE_ARRIVED.value,
            direction=direction.value,
            event_id=event_id,
            details={
                'vehicle_id': vehicle_id,
                'vehicle_type': vehicle_type.value,
                'priority': VEHICLE_PRIORITY.get(vehicle_type, 10),
                'sequence_no': sequence_no,
            },
            reason=f"{vehicle_type.value} arrived from {direction.value}",
        )

        # Check if this is an emergency vehicle
        if vehicle_type == VehicleType.EMERGENCY:
            self._handle_emergency_arrival(junction, direction, vehicle_id, event_id)

        queue_count = self._queue_repo.get_queue_counts(junction)

        logger.info(
            f"Vehicle {vehicle_id} ({vehicle_type.value}) arrived at "
            f"{junction.junction_id}/{direction.value}. "
            f"Queue: {queue_count.get(direction.value, 0)}"
        )

        return {
            'status': ProcessingStatus.ACCEPTED.value,
            'event_id': event_id,
            'message': f'Vehicle {vehicle_id} added to {direction.value} queue',
            'queue_count': queue_count.get(direction.value, 0),
        }

    def _process_clearance(
        self,
        junction,
        direction: Direction,
        vehicle_id: str,
        cleared_at: datetime,
        event_id: str,
        sequence_no: int = None,
    ) -> Dict:
        """Process a vehicle clearance event."""
        # Inspect the vehicle before removal so we can detect whether this
        # clearance releases an active emergency (clearance events do not
        # carry vehicle_type, so the type must be read from the queue row).
        waiting = self._queue_repo.get_vehicle_by_id(junction, vehicle_id)
        is_emergency_vehicle = (
            waiting is not None
            and waiting.vehicle_type == VehicleType.EMERGENCY.value
        )

        removed = self._queue_repo.remove_vehicle(junction, vehicle_id)

        if not removed:
            # Vehicle not found — could be out-of-order clearance
            # or clearance without prior arrival. Log but accept.
            self._audit_repo.log(
                junction=junction,
                event_type=AuditEventType.VEHICLE_CLEARED.value,
                direction=direction.value,
                event_id=event_id,
                details={
                    'vehicle_id': vehicle_id,
                    'sequence_no': sequence_no,
                    'warning': 'Vehicle not found in queue (no matching arrival)',
                },
                reason=f"Clearance for unknown vehicle {vehicle_id}",
            )
            logger.warning(
                f"Clearance for vehicle {vehicle_id} not found in queue "
                f"at {junction.junction_id}/{direction.value}"
            )
            return {
                'status': ProcessingStatus.ACCEPTED.value,
                'event_id': event_id,
                'message': (
                    f'Vehicle {vehicle_id} clearance accepted '
                    f'(vehicle was not in queue)'
                ),
                'warning': 'Vehicle not found in queue',
            }

        self._audit_repo.log(
            junction=junction,
            event_type=AuditEventType.VEHICLE_CLEARED.value,
            direction=direction.value,
            event_id=event_id,
            details={
                'vehicle_id': vehicle_id,
                'sequence_no': sequence_no,
            },
            reason=f"Vehicle {vehicle_id} cleared from {direction.value}",
        )

        # If the cleared vehicle was the active emergency, release emergency
        # mode and return the junction to automatic scheduling. This matches
        # the documented policy: emergency persists until the emergency
        # vehicle leaves (or an operator releases control).
        if removed and is_emergency_vehicle:
            state = self._state_repo.get_snapshot(junction.junction_id)
            if state.active_emergency_direction == direction:
                now = self._clock.now()
                next_transition_at = None
                if state.transition_state == TransitionState.STABLE:
                    next_transition_at = now + timedelta(
                        seconds=DEFAULT_GREEN_DURATION
                    )
                self._state_repo.update_state(
                    junction_id=junction.junction_id,
                    expected_version=state.version,
                    active_emergency_direction=False,
                    mode=OperatingMode.AUTOMATIC,
                    next_transition_at=next_transition_at,
                )
                self._audit_repo.log(
                    junction=junction,
                    event_type=AuditEventType.EMERGENCY_CLEARED.value,
                    direction=direction.value,
                    event_id=event_id,
                    details={
                        'vehicle_id': vehicle_id,
                        'reason': 'Emergency vehicle cleared from queue',
                    },
                    reason="Emergency cleared; returned to AUTOMATIC mode",
                )
                logger.info(
                    f"Emergency cleared at {junction.junction_id}/{direction.value}; "
                    f"returned to AUTOMATIC"
                )

        queue_count = self._queue_repo.get_queue_counts(junction)
        logger.info(
            f"Vehicle {vehicle_id} cleared from "
            f"{junction.junction_id}/{direction.value}. "
            f"Queue: {queue_count.get(direction.value, 0)}"
        )

        return {
            'status': ProcessingStatus.ACCEPTED.value,
            'event_id': event_id,
            'message': f'Vehicle {vehicle_id} cleared from {direction.value} queue',
            'queue_count': queue_count.get(direction.value, 0),
        }

    def _handle_emergency_arrival(
        self, junction, direction: Direction, vehicle_id: str, event_id: str
    ):
        """Handle emergency vehicle arrival — trigger preemption if needed."""
        from traffic.application.command_service import CommandService
        cmd_service = CommandService(clock=self._clock)
        try:
            cmd_service.handle_emergency(junction.junction_id, direction, vehicle_id, event_id)
        except Exception as e:
            logger.error(
                f"Failed to handle emergency for {vehicle_id} at "
                f"{junction.junction_id}/{direction.value}: {e}"
            )
            # Surface the failed preemption in the audit trail. The arrival
            # itself is still accepted (the vehicle physically arrived and is
            # queued), but operators must be able to see that preemption did
            # not take effect rather than assuming the emergency was handled.
            self._audit_repo.log(
                junction=junction,
                event_type=AuditEventType.EMERGENCY_DETECTED.value,
                direction=direction.value,
                event_id=event_id,
                details={
                    'vehicle_id': vehicle_id,
                    'preemption_failed': True,
                    'error': str(e),
                },
                reason=(
                    f"Emergency preemption FAILED for {vehicle_id}; "
                    f"vehicle queued without preemption ({e})"
                ),
            )

