"""
Django ORM models for the Factory Traffic Management System.

These models handle persistence only. Domain logic lives in traffic.domain.
"""
import json
import uuid
from django.db import models
from django.utils import timezone


class Junction(models.Model):
    """A traffic junction."""
    junction_id = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    phase_config = models.JSONField(
        default=list,
        help_text="List of phase configurations: [{phase, directions}, ...]"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['junction_id']

    def __str__(self):
        return f"Junction {self.junction_id} ({self.name})"


class JunctionState(models.Model):
    """
    Current state of a junction.
    Mutable — updated on every state transition.
    Uses version field for optimistic concurrency control.
    """
    junction = models.OneToOneField(
        Junction, on_delete=models.CASCADE, related_name='state'
    )
    mode = models.CharField(
        max_length=20, default='AUTOMATIC',
        help_text="Operating mode: AUTOMATIC, MANUAL, EMERGENCY, DEGRADED"
    )
    current_phase = models.CharField(
        max_length=20, default='NORTH_SOUTH',
        help_text="Current active phase: NORTH_SOUTH, EAST_WEST"
    )
    transition_state = models.CharField(
        max_length=20, default='STABLE',
        help_text="Transition state: STABLE, YELLOW, ALL_RED, TRANSITIONING"
    )
    desired_signals = models.JSONField(
        default=dict,
        help_text='Desired signal state: {"NORTH": "GREEN", ...}'
    )
    actual_signals = models.JSONField(
        default=dict,
        help_text='Controller-confirmed signal state: {"NORTH": "GREEN", ...}'
    )
    controller_health = models.CharField(
        max_length=20, default='ONLINE',
        help_text="Controller health: ONLINE, OFFLINE, DEGRADED, WARNING, UNKNOWN"
    )
    active_emergency_direction = models.CharField(
        max_length=10, null=True, blank=True,
        help_text="Direction of active emergency, or null"
    )
    manual_direction = models.CharField(
        max_length=10, null=True, blank=True,
        help_text="Direction of manual GREEN request, or null"
    )
    next_transition_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the next automatic transition is due"
    )
    phase_started_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the current phase became STABLE GREEN"
    )
    version = models.IntegerField(
        default=1,
        help_text="Optimistic concurrency version counter"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Junction State"
        verbose_name_plural = "Junction States"

    def __str__(self):
        return (
            f"State({self.junction.junction_id}): "
            f"{self.mode} {self.current_phase} {self.transition_state}"
        )


class WaitingVehicle(models.Model):
    """A vehicle currently waiting in a junction queue."""
    junction = models.ForeignKey(
        Junction, on_delete=models.CASCADE, related_name='waiting_vehicles'
    )
    direction = models.CharField(max_length=10)
    vehicle_id = models.CharField(max_length=100)
    vehicle_type = models.CharField(max_length=30)
    priority = models.IntegerField(default=10)
    arrived_at = models.DateTimeField()
    event_id = models.CharField(max_length=100, db_index=True)

    class Meta:
        unique_together = [('junction', 'vehicle_id')]
        ordering = ['-priority', 'arrived_at']
        indexes = [
            models.Index(fields=['junction', 'direction']),
        ]

    def __str__(self):
        return f"{self.vehicle_id} ({self.vehicle_type}) @ {self.direction}"


class ProcessedEvent(models.Model):
    """
    Record of a processed sensor event.
    The event_id unique constraint enforces idempotency at the database level.
    """
    event_id = models.CharField(max_length=100, unique=True, db_index=True)
    junction = models.ForeignKey(
        Junction, on_delete=models.CASCADE, related_name='processed_events'
    )
    direction = models.CharField(max_length=10, null=True, blank=True)
    event_type = models.CharField(max_length=30)
    vehicle_id = models.CharField(max_length=100, null=True, blank=True)
    vehicle_type = models.CharField(max_length=30, null=True, blank=True)
    sequence_no = models.IntegerField(null=True, blank=True)
    sensor_timestamp = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20, default='ACCEPTED',
        help_text="ACCEPTED, DUPLICATE, REJECTED"
    )
    rejection_reason = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['junction', 'event_type']),
        ]

    def __str__(self):
        return f"Event {self.event_id}: {self.status}"


class ControllerCommand(models.Model):
    """
    A command sent to a physical traffic controller.
    Tracks desired state changes and their acknowledgements.
    """
    command_id = models.CharField(max_length=100, unique=True, db_index=True)
    junction = models.ForeignKey(
        Junction, on_delete=models.CASCADE, related_name='controller_commands'
    )
    direction = models.CharField(max_length=10, null=True, blank=True)
    requested_signals = models.JSONField(
        default=dict,
        help_text='Requested signal vector: {"NORTH": "GREEN", ...}'
    )
    status = models.CharField(
        max_length=20, default='PENDING',
        help_text="PENDING, SENT, ACKNOWLEDGED, FAILED, TIMED_OUT, SUPERSEDED"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    acked_at = models.DateTimeField(null=True, blank=True)
    timeout_at = models.DateTimeField(null=True, blank=True)
    actual_signals_on_ack = models.JSONField(
        null=True, blank=True,
        help_text="Actual signals reported by controller on ACK"
    )
    failure_reason = models.TextField(null=True, blank=True)
    is_simulated = models.BooleanField(
        default=True,
        help_text="Whether this is from the simulated controller (vs real hardware)"
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['junction', 'status']),
        ]

    def __str__(self):
        return f"Command {self.command_id}: {self.status}"


class AuditEntry(models.Model):
    """
    Append-only audit trail for system events.
    Separate from current-state representation.
    """
    junction = models.ForeignKey(
        Junction, on_delete=models.CASCADE, related_name='audit_entries'
    )
    event_type = models.CharField(max_length=50, db_index=True)
    direction = models.CharField(max_length=10, null=True, blank=True)
    previous_state = models.CharField(max_length=50, null=True, blank=True)
    new_state = models.CharField(max_length=50, null=True, blank=True)
    event_id = models.CharField(max_length=100, null=True, blank=True)
    command_id = models.CharField(max_length=100, null=True, blank=True)
    details = models.JSONField(
        default=dict,
        help_text="Additional context for the audit entry"
    )
    reason = models.TextField(null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['junction', 'event_type']),
            models.Index(fields=['junction', '-timestamp']),
        ]
        verbose_name_plural = "Audit entries"

    def __str__(self):
        return f"Audit({self.junction.junction_id}): {self.event_type} @ {self.timestamp}"

