"""
DRF Serializers for the Traffic Management System API.
"""
from rest_framework import serializers

from traffic.domain.enums import (
    CommandType,
    Direction,
    EventType,
    VehicleType,
)


class JunctionCreateSerializer(serializers.Serializer):
    """Serializer for creating a junction."""
    junction_id = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=200)
    phase_config = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="Phase config list. Defaults to standard NORTH_SOUTH/EAST_WEST."
    )


class JunctionSerializer(serializers.Serializer):
    """Serializer for junction responses."""
    junction_id = serializers.CharField()
    name = serializers.CharField()
    phase_config = serializers.ListField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class SensorEventSerializer(serializers.Serializer):
    """Serializer for incoming sensor events."""
    event_id = serializers.CharField(max_length=100)
    junction_id = serializers.CharField(max_length=50)
    direction = serializers.ChoiceField(
        choices=[(d.value, d.value) for d in Direction]
    )
    event_type = serializers.ChoiceField(
        choices=[(e.value, e.value) for e in EventType]
    )
    vehicle_id = serializers.CharField(max_length=100, required=False, allow_blank=True)
    vehicle_type = serializers.ChoiceField(
        choices=[(v.value, v.value) for v in VehicleType],
        required=False,
        allow_blank=True,
    )
    sequence_no = serializers.IntegerField(required=False, allow_null=True)
    timestamp = serializers.CharField(required=False, allow_blank=True)


class CommandSerializer(serializers.Serializer):
    """Serializer for control commands."""
    command = serializers.ChoiceField(
        choices=[(c.value, c.value) for c in CommandType]
    )
    direction = serializers.ChoiceField(
        choices=[(d.value, d.value) for d in Direction],
        required=False,
        allow_blank=True,
    )


class ControllerEventSerializer(serializers.Serializer):
    """Serializer for controller events (ACK/status)."""
    # For command ACKs
    command_id = serializers.CharField(max_length=100, required=False)
    junction_id = serializers.CharField(max_length=50, required=False)
    status = serializers.CharField(max_length=20)
    actual_state = serializers.CharField(max_length=20, required=False)
    actual_signals = serializers.DictField(
        child=serializers.CharField(),
        required=False,
    )
    timestamp = serializers.CharField(required=False)

    # For device status events
    event_id = serializers.CharField(max_length=100, required=False)
    device_type = serializers.CharField(max_length=30, required=False)
    direction = serializers.CharField(max_length=10, required=False)
    reason = serializers.CharField(required=False)


class JunctionStatusSerializer(serializers.Serializer):
    """Serializer for junction status responses."""
    junction_id = serializers.CharField()
    mode = serializers.CharField()
    phase = serializers.CharField()
    transition_state = serializers.CharField()
    controller_status = serializers.CharField()
    desired_signals = serializers.DictField()
    actual_signals = serializers.DictField()
    queues = serializers.DictField()
    active_emergency = serializers.CharField(allow_null=True)
    manual_direction = serializers.CharField(allow_null=True)
    next_transition_at = serializers.DateTimeField(allow_null=True)
    phase_started_at = serializers.DateTimeField(allow_null=True)
    pending_commands = serializers.ListField(required=False)


class AuditEntrySerializer(serializers.Serializer):
    """Serializer for audit history entries."""
    id = serializers.IntegerField()
    event_type = serializers.CharField()
    direction = serializers.CharField(allow_null=True)
    previous_state = serializers.CharField(allow_null=True)
    new_state = serializers.CharField(allow_null=True)
    event_id = serializers.CharField(allow_null=True)
    command_id = serializers.CharField(allow_null=True)
    details = serializers.DictField()
    reason = serializers.CharField(allow_null=True)
    timestamp = serializers.DateTimeField()


class ControllerCommandSerializer(serializers.Serializer):
    """Serializer for controller command details."""
    command_id = serializers.CharField()
    direction = serializers.CharField(allow_null=True)
    requested_signals = serializers.DictField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    sent_at = serializers.DateTimeField(allow_null=True)
    acked_at = serializers.DateTimeField(allow_null=True)
    timeout_at = serializers.DateTimeField(allow_null=True)
    actual_signals_on_ack = serializers.DictField(allow_null=True)
    failure_reason = serializers.CharField(allow_null=True)
    is_simulated = serializers.BooleanField()

