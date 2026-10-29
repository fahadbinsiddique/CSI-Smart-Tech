"""
API views for the Factory Traffic Management System.
"""
import logging
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from traffic.api.serializers import (
    AuditEntrySerializer,
    CommandSerializer,
    ControllerCommandSerializer,
    ControllerEventSerializer,
    JunctionCreateSerializer,
    JunctionSerializer,
    JunctionStatusSerializer,
    SensorEventSerializer,
)
from traffic.application.command_service import CommandService
from traffic.application.controller_service import ControllerService
from traffic.application.event_service import EventService
from traffic.domain.enums import Direction
from traffic.domain.exceptions import (
    DomainError,
    InvalidCommandError,
    InvalidEventError,
    JunctionNotFoundError,
)
from traffic.infrastructure.repositories import (
    AuditRepository,
    CommandRepository,
    JunctionRepository,
    JunctionStateRepository,
    QueueRepository,
)

logger = logging.getLogger('traffic.api')


# ── Junction Endpoints ──────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
def junction_list(request):
    """
    GET  /api/junctions/      — List all junctions
    POST /api/junctions/      — Create a new junction
    """
    if request.method == 'GET':
        repo = JunctionRepository()
        junctions = repo.get_all()
        data = []
        for j in junctions:
            data.append({
                'junction_id': j.junction_id,
                'name': j.name,
                'phase_config': j.phase_config,
                'created_at': j.created_at,
                'updated_at': j.updated_at,
            })
        return Response(data)

    elif request.method == 'POST':
        serializer = JunctionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': 'Validation failed', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data
        repo = JunctionRepository()

        if repo.exists(data['junction_id']):
            return Response(
                {'error': f"Junction '{data['junction_id']}' already exists"},
                status=status.HTTP_409_CONFLICT,
            )

        junction = repo.create(
            junction_id=data['junction_id'],
            name=data['name'],
            phase_config=data.get('phase_config'),
        )

        return Response(
            {
                'junction_id': junction.junction_id,
                'name': junction.name,
                'phase_config': junction.phase_config,
                'created_at': junction.created_at,
                'updated_at': junction.updated_at,
            },
            status=status.HTTP_201_CREATED,
        )


@api_view(['GET'])
def junction_detail(request, junction_id):
    """GET /api/junctions/<id>/ — Get junction details."""
    repo = JunctionRepository()
    junction = repo.get_by_id(junction_id)
    return Response({
        'junction_id': junction.junction_id,
        'name': junction.name,
        'phase_config': junction.phase_config,
        'created_at': junction.created_at,
        'updated_at': junction.updated_at,
    })


# ── Sensor Events Endpoint ──────────────────────────────────────────────────

@api_view(['POST'])
def sensor_events(request):
    """POST /api/sensor-events/ — Submit a sensor event."""
    serializer = SensorEventSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {'error': 'Validation failed', 'details': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    service = EventService()
    result = service.process_sensor_event(serializer.validated_data)

    if result['status'] == 'DUPLICATE':
        return Response(result, status=status.HTTP_200_OK)

    return Response(result, status=status.HTTP_201_CREATED)


# ── Junction Status Endpoint ────────────────────────────────────────────────

@api_view(['GET'])
def junction_status(request, junction_id):
    """GET /api/junctions/<id>/status/ — Get junction status."""
    state_repo = JunctionStateRepository()
    cmd_repo = CommandRepository()
    junction_repo = JunctionRepository()

    junction = junction_repo.get_by_id(junction_id)
    state = state_repo.get_snapshot(junction_id)

    # Get pending commands
    pending_cmds = cmd_repo.get_pending_commands(junction)
    pending_cmd_data = [
        {
            'command_id': cmd.command_id,
            'requested_signals': cmd.requested_signals,
            'status': cmd.status,
            'created_at': cmd.created_at,
            'timeout_at': cmd.timeout_at,
        }
        for cmd in pending_cmds
    ]

    response_data = {
        'junction_id': junction_id,
        'mode': state.mode.value,
        'phase': state.current_phase.value,
        'transition_state': state.transition_state.value,
        'controller_status': state.controller_health.value,
        'desired_signals': state.desired_signals.as_dict(),
        'actual_signals': state.actual_signals.as_dict(),
        'queues': {d.value: state.queues.get(d, 0) for d in Direction},
        'active_emergency': (
            state.active_emergency_direction.value
            if state.active_emergency_direction else None
        ),
        'manual_direction': (
            state.manual_direction.value
            if state.manual_direction else None
        ),
        'next_transition_at': state.next_transition_at,
        'phase_started_at': state.phase_started_at,
        'pending_commands': pending_cmd_data,
    }

    return Response(response_data)


# ── Control Commands Endpoint ────────────────────────────────────────────────

@api_view(['POST'])
def junction_commands(request, junction_id):
    """POST /api/junctions/<id>/commands/ — Submit a control command."""
    serializer = CommandSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {'error': 'Validation failed', 'details': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    service = CommandService()
    result = service.process_command(junction_id, serializer.validated_data)

    return Response(result, status=status.HTTP_200_OK)


# ── Controller Events Endpoint ──────────────────────────────────────────────

@api_view(['POST'])
def controller_events(request):
    """POST /api/controller-events/ — Submit a controller event (ACK/status)."""
    serializer = ControllerEventSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {'error': 'Validation failed', 'details': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    service = ControllerService()
    result = service.process_controller_event(serializer.validated_data)

    response_status = (
        status.HTTP_200_OK
        if result.get('status') != 'rejected'
        else status.HTTP_400_BAD_REQUEST
    )
    return Response(result, status=response_status)


# ── History Endpoint ─────────────────────────────────────────────────────────

@api_view(['GET'])
def junction_history(request, junction_id):
    """GET /api/junctions/<id>/history/ — Get junction audit history."""
    junction_repo = JunctionRepository()
    junction = junction_repo.get_by_id(junction_id)

    limit = request.query_params.get('limit', 50)
    try:
        limit = min(int(limit), 200)
    except (ValueError, TypeError):
        limit = 50

    event_type = request.query_params.get('event_type')

    audit_repo = AuditRepository()
    entries = audit_repo.get_history(junction, limit=limit, event_type=event_type)

    data = [
        {
            'id': e.id,
            'event_type': e.event_type,
            'direction': e.direction,
            'previous_state': e.previous_state,
            'new_state': e.new_state,
            'event_id': e.event_id,
            'command_id': e.command_id,
            'details': e.details,
            'reason': e.reason,
            'timestamp': e.timestamp,
        }
        for e in entries
    ]

    return Response({
        'junction_id': junction_id,
        'count': len(data),
        'history': data,
    })


# ── Health Check ─────────────────────────────────────────────────────────────

@api_view(['GET'])
def health_check(request):
    """GET /api/health/ — Simple health check."""
    return Response({'status': 'ok'})

