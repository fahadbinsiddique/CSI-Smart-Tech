"""
API and integration tests for the Traffic Management System.

These tests use Django's test framework and require database access.
"""
import json
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from traffic.infrastructure.models import (
    Junction,
    JunctionState,
    WaitingVehicle,
    ProcessedEvent,
    ControllerCommand,
    AuditEntry,
)
from traffic.domain.enums import (
    CommandStatus,
    DeviceHealth,
    Direction,
    OperatingMode,
    Phase,
    SignalState,
    TransitionState,
)
from traffic.domain.models import SignalVector


class JunctionAPITest(TestCase):
    """Tests for junction CRUD endpoints."""

    def setUp(self):
        self.client = APIClient()

    def test_create_junction(self):
        """POST /api/junctions/ creates a junction with initial state."""
        response = self.client.post('/api/junctions/', {
            'junction_id': 'A',
            'name': 'Junction A',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['junction_id'], 'A')

        # Verify initial state was created
        state = JunctionState.objects.get(junction__junction_id='A')
        self.assertEqual(state.mode, 'AUTOMATIC')
        self.assertEqual(state.current_phase, 'NORTH_SOUTH')
        self.assertEqual(state.transition_state, 'STABLE')

    def test_create_duplicate_junction(self):
        """Creating a junction with duplicate ID returns 409."""
        self.client.post('/api/junctions/', {
            'junction_id': 'A', 'name': 'J-A'
        }, format='json')
        response = self.client.post('/api/junctions/', {
            'junction_id': 'A', 'name': 'J-A-dup'
        }, format='json')
        self.assertEqual(response.status_code, 409)

    def test_list_junctions(self):
        """GET /api/junctions/ returns all junctions."""
        self.client.post('/api/junctions/', {
            'junction_id': 'A', 'name': 'J-A'
        }, format='json')
        response = self.client.get('/api/junctions/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_get_junction_detail(self):
        """GET /api/junctions/<id>/ returns junction details."""
        self.client.post('/api/junctions/', {
            'junction_id': 'A', 'name': 'J-A'
        }, format='json')
        response = self.client.get('/api/junctions/A/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['junction_id'], 'A')

    def test_get_unknown_junction(self):
        """GET /api/junctions/<unknown>/ returns 404."""
        response = self.client.get('/api/junctions/UNKNOWN/')
        self.assertEqual(response.status_code, 404)


class SensorEventAPITest(TestCase):
    """Tests for sensor event processing endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.client.post('/api/junctions/', {
            'junction_id': 'A', 'name': 'J-A'
        }, format='json')

    def test_vehicle_arrival(self):
        """POST /api/sensor-events/ with VEHICLE_ARRIVED adds to queue."""
        response = self.client.post('/api/sensor-events/', {
            'event_id': 'evt-1001',
            'junction_id': 'A',
            'direction': 'NORTH',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-501',
            'vehicle_type': 'FORKLIFT',
            'sequence_no': 1501,
            'timestamp': '2026-10-05T10:15:20Z',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'ACCEPTED')

        # Verify queue
        self.assertEqual(
            WaitingVehicle.objects.filter(
                junction__junction_id='A', direction='NORTH'
            ).count(),
            1,
        )

    def test_duplicate_event(self):
        """Duplicate event_id returns 200 DUPLICATE without mutating queue."""
        event_data = {
            'event_id': 'evt-1001',
            'junction_id': 'A',
            'direction': 'NORTH',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-501',
            'vehicle_type': 'FORKLIFT',
        }
        # First submission
        r1 = self.client.post('/api/sensor-events/', event_data, format='json')
        self.assertEqual(r1.status_code, 201)

        # Duplicate submission
        r2 = self.client.post('/api/sensor-events/', event_data, format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data['status'], 'DUPLICATE')

        # Queue should still have exactly 1 vehicle
        self.assertEqual(
            WaitingVehicle.objects.filter(
                junction__junction_id='A', direction='NORTH'
            ).count(),
            1,
        )

    def test_vehicle_clearance(self):
        """VEHICLE_CLEARED removes vehicle from queue."""
        # Arrive
        self.client.post('/api/sensor-events/', {
            'event_id': 'evt-1001',
            'junction_id': 'A',
            'direction': 'NORTH',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-501',
            'vehicle_type': 'FORKLIFT',
        }, format='json')

        # Clear
        response = self.client.post('/api/sensor-events/', {
            'event_id': 'evt-1002',
            'junction_id': 'A',
            'direction': 'NORTH',
            'event_type': 'VEHICLE_CLEARED',
            'vehicle_id': 'VH-501',
        }, format='json')
        self.assertEqual(response.status_code, 201)

        # Queue should be empty
        self.assertEqual(
            WaitingVehicle.objects.filter(
                junction__junction_id='A', direction='NORTH'
            ).count(),
            0,
        )

    def test_clearance_without_arrival(self):
        """Clearance for non-existent vehicle is accepted with warning."""
        response = self.client.post('/api/sensor-events/', {
            'event_id': 'evt-1003',
            'junction_id': 'A',
            'direction': 'NORTH',
            'event_type': 'VEHICLE_CLEARED',
            'vehicle_id': 'VH-UNKNOWN',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'ACCEPTED')
        self.assertIn('warning', response.data)

    def test_invalid_direction(self):
        """Invalid direction returns 400."""
        response = self.client.post('/api/sensor-events/', {
            'event_id': 'evt-1004',
            'junction_id': 'A',
            'direction': 'NORTHWEST',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-1',
            'vehicle_type': 'TRUCK',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_invalid_vehicle_type(self):
        """Invalid vehicle type returns 400."""
        response = self.client.post('/api/sensor-events/', {
            'event_id': 'evt-1005',
            'junction_id': 'A',
            'direction': 'NORTH',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-1',
            'vehicle_type': 'BICYCLE',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_unknown_junction(self):
        """Unknown junction returns 400."""
        response = self.client.post('/api/sensor-events/', {
            'event_id': 'evt-1006',
            'junction_id': 'UNKNOWN',
            'direction': 'NORTH',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-1',
            'vehicle_type': 'TRUCK',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_missing_fields(self):
        """Missing required fields returns 400."""
        response = self.client.post('/api/sensor-events/', {
            'event_id': 'evt-1007',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_queue_never_goes_negative(self):
        """Queue count should never go negative."""
        # Clear without arrival
        self.client.post('/api/sensor-events/', {
            'event_id': 'evt-clear-1',
            'junction_id': 'A',
            'direction': 'EAST',
            'event_type': 'VEHICLE_CLEARED',
            'vehicle_id': 'VH-PHANTOM',
        }, format='json')

        # Check queue
        status_response = self.client.get('/api/junctions/A/status/')
        self.assertGreaterEqual(status_response.data['queues']['EAST'], 0)

    @patch('traffic.application.command_service.CommandService.handle_emergency')
    def test_emergency_preemption_failure_is_audited_not_silent(self, mock_handle):
        """
        If emergency preemption fails (e.g. concurrency conflict), the arrival
        is still accepted and the vehicle is queued, but the failure is
        recorded in the audit trail instead of being silently swallowed.
        """
        mock_handle.side_effect = RuntimeError('state version conflict')

        response = self.client.post('/api/sensor-events/', {
            'event_id': 'evt-emg-fail',
            'junction_id': 'A',
            'direction': 'EAST',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'EMG-FAIL-1',
            'vehicle_type': 'EMERGENCY',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'ACCEPTED')

        # The vehicle is still queued (reality is recorded even if preemption failed).
        self.assertEqual(
            WaitingVehicle.objects.filter(
                junction__junction_id='A', vehicle_id='EMG-FAIL-1'
            ).count(),
            1,
        )

        # The failed preemption must be visible in the audit trail.
        entries = AuditEntry.objects.filter(
            junction__junction_id='A',
            event_type='EMERGENCY_DETECTED',
        )
        self.assertTrue(entries.exists())
        entry = entries.order_by('-id').first()
        self.assertTrue(entry.details.get('preemption_failed'))
        self.assertIn('state version conflict', entry.reason)


class JunctionStatusAPITest(TestCase):
    """Tests for junction status endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.client.post('/api/junctions/', {
            'junction_id': 'A', 'name': 'J-A'
        }, format='json')

    def test_get_status(self):
        """GET /api/junctions/A/status/ returns complete status."""
        response = self.client.get('/api/junctions/A/status/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['junction_id'], 'A')
        self.assertEqual(response.data['mode'], 'AUTOMATIC')
        self.assertEqual(response.data['phase'], 'NORTH_SOUTH')
        self.assertIn('desired_signals', response.data)
        self.assertIn('actual_signals', response.data)
        self.assertIn('queues', response.data)

    def test_status_reflects_queue_changes(self):
        """Status queues update after vehicle events."""
        self.client.post('/api/sensor-events/', {
            'event_id': 'evt-q1',
            'junction_id': 'A',
            'direction': 'EAST',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-1',
            'vehicle_type': 'TRUCK',
        }, format='json')

        response = self.client.get('/api/junctions/A/status/')
        self.assertEqual(response.data['queues']['EAST'], 1)

    def test_unknown_junction_status(self):
        """Status for unknown junction returns 404."""
        response = self.client.get('/api/junctions/UNKNOWN/status/')
        self.assertEqual(response.status_code, 404)


class ManualControlAPITest(TestCase):
    """Tests for manual control commands."""

    def setUp(self):
        self.client = APIClient()
        self.client.post('/api/junctions/', {
            'junction_id': 'A', 'name': 'J-A'
        }, format='json')

    def test_manual_green_request(self):
        """POST manual GREEN request is accepted."""
        response = self.client.post('/api/junctions/A/commands/', {
            'command': 'MANUAL_GREEN_REQUEST',
            'direction': 'NORTH',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'accepted')

        # Verify mode changed
        status = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status.data['mode'], 'MANUAL')

    def test_return_to_automatic(self):
        """POST return to automatic is accepted."""
        # First enter manual
        self.client.post('/api/junctions/A/commands/', {
            'command': 'MANUAL_GREEN_REQUEST',
            'direction': 'NORTH',
        }, format='json')

        # Return to automatic
        response = self.client.post('/api/junctions/A/commands/', {
            'command': 'RETURN_TO_AUTOMATIC',
        }, format='json')
        self.assertEqual(response.status_code, 200)

    def test_invalid_command(self):
        """Invalid command type returns 400."""
        response = self.client.post('/api/junctions/A/commands/', {
            'command': 'INVALID_COMMAND',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_missing_direction_for_manual_green(self):
        """Missing direction for MANUAL_GREEN_REQUEST returns 400."""
        response = self.client.post('/api/junctions/A/commands/', {
            'command': 'MANUAL_GREEN_REQUEST',
        }, format='json')
        self.assertEqual(response.status_code, 400)


class ControllerEventAPITest(TestCase):
    """Tests for controller event/ACK processing."""

    def setUp(self):
        self.client = APIClient()
        self.client.post('/api/junctions/', {
            'junction_id': 'A', 'name': 'J-A'
        }, format='json')

    def test_valid_ack(self):
        """Valid ACK updates actual signals."""
        # Create a pending command
        junction = Junction.objects.get(junction_id='A')
        cmd = ControllerCommand.objects.create(
            command_id='cmd-test-1',
            junction=junction,
            requested_signals={
                'NORTH': 'GREEN', 'SOUTH': 'GREEN',
                'EAST': 'RED', 'WEST': 'RED'
            },
            status='PENDING',
        )

        response = self.client.post('/api/controller-events/', {
            'command_id': 'cmd-test-1',
            'junction_id': 'A',
            'status': 'ACK',
            'actual_signals': {
                'NORTH': 'GREEN', 'SOUTH': 'GREEN',
                'EAST': 'RED', 'WEST': 'RED'
            },
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'accepted')

        # Verify command was acknowledged
        cmd.refresh_from_db()
        self.assertEqual(cmd.status, 'ACKNOWLEDGED')

    def test_unknown_command_ack(self):
        """ACK for unknown command_id is rejected."""
        response = self.client.post('/api/controller-events/', {
            'command_id': 'cmd-unknown',
            'junction_id': 'A',
            'status': 'ACK',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_duplicate_ack(self):
        """Duplicate ACK for already-acknowledged command is rejected."""
        junction = Junction.objects.get(junction_id='A')
        cmd = ControllerCommand.objects.create(
            command_id='cmd-dup-1',
            junction=junction,
            requested_signals={'NORTH': 'GREEN', 'SOUTH': 'GREEN',
                             'EAST': 'RED', 'WEST': 'RED'},
            status='ACKNOWLEDGED',
        )

        response = self.client.post('/api/controller-events/', {
            'command_id': 'cmd-dup-1',
            'junction_id': 'A',
            'status': 'ACK',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_controller_offline_event(self):
        """Controller OFFLINE event puts junction in DEGRADED mode."""
        response = self.client.post('/api/controller-events/', {
            'event_id': 'status-1',
            'junction_id': 'A',
            'device_type': 'SIGNAL_CONTROLLER',
            'status': 'OFFLINE',
        }, format='json')
        self.assertEqual(response.status_code, 200)

        # Verify mode changed
        status = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status.data['mode'], 'DEGRADED')
        self.assertEqual(status.data['controller_status'], 'OFFLINE')

    def test_nack_response(self):
        """NACK from controller marks command as FAILED."""
        junction = Junction.objects.get(junction_id='A')
        cmd = ControllerCommand.objects.create(
            command_id='cmd-nack-1',
            junction=junction,
            requested_signals={'NORTH': 'GREEN', 'SOUTH': 'GREEN',
                             'EAST': 'RED', 'WEST': 'RED'},
            status='PENDING',
        )

        response = self.client.post('/api/controller-events/', {
            'command_id': 'cmd-nack-1',
            'junction_id': 'A',
            'status': 'NACK',
            'reason': 'Hardware fault',
        }, format='json')
        self.assertEqual(response.status_code, 200)

        cmd.refresh_from_db()
        self.assertEqual(cmd.status, 'FAILED')


class ControllerACKValidationTest(TestCase):
    """Tests that controller ACKs are validated against commanded signals."""

    def setUp(self):
        self.client = APIClient()
        self.client.post('/api/junctions/', {
            'junction_id': 'A', 'name': 'J-A'
        }, format='json')
        self.junction = Junction.objects.get(junction_id='A')

    def test_ack_with_matching_signals_is_acknowledged(self):
        """ACK confirming exactly the requested signals succeeds."""
        cmd = ControllerCommand.objects.create(
            command_id='cmd-match-1',
            junction=self.junction,
            requested_signals={
                'NORTH': 'GREEN', 'SOUTH': 'GREEN',
                'EAST': 'RED', 'WEST': 'RED'
            },
            status='PENDING',
        )
        response = self.client.post('/api/controller-events/', {
            'command_id': 'cmd-match-1',
            'junction_id': 'A',
            'status': 'ACK',
            'actual_signals': {
                'NORTH': 'GREEN', 'SOUTH': 'GREEN',
                'EAST': 'RED', 'WEST': 'RED'
            },
        }, format='json')
        self.assertEqual(response.status_code, 200)
        cmd.refresh_from_db()
        self.assertEqual(cmd.status, 'ACKNOWLEDGED')

        status = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status.data['controller_status'], 'ONLINE')
        self.assertEqual(status.data['actual_signals'], {
            'NORTH': 'GREEN', 'SOUTH': 'GREEN',
            'EAST': 'RED', 'WEST': 'RED'
        })

    def test_ack_with_conflicting_signals_is_rejected(self):
        """
        ACK confirming a DIFFERENT state than commanded must not be treated
        as a confirmed physical state. The command is marked FAILED, actual
        signals are left unchanged, and controller health degrades to WARNING.
        """
        cmd = ControllerCommand.objects.create(
            command_id='cmd-mismatch-1',
            junction=self.junction,
            direction='EAST',
            requested_signals={
                'NORTH': 'RED', 'SOUTH': 'RED',
                'EAST': 'GREEN', 'WEST': 'GREEN'
            },
            status='PENDING',
        )

        # The junction's actual state is currently NORTH_SOUTH GREEN (initial).
        state_before = self.client.get('/api/junctions/A/status/')
        self.assertEqual(state_before.data['actual_signals']['NORTH'], 'GREEN')

        # Controller claims it executed NORTH_SOUTH GREEN — different from the
        # EAST_WEST GREEN we commanded. Confirming this would falsely represent
        # physical state.
        response = self.client.post('/api/controller-events/', {
            'command_id': 'cmd-mismatch-1',
            'junction_id': 'A',
            'status': 'ACK',
            'actual_signals': {
                'NORTH': 'GREEN', 'SOUTH': 'GREEN',
                'EAST': 'RED', 'WEST': 'RED'
            },
        }, format='json')
        self.assertEqual(response.status_code, 200)

        cmd.refresh_from_db()
        self.assertEqual(cmd.status, 'FAILED')
        self.assertIn('mismatch', cmd.failure_reason)

        # The mismatch is recorded in the audit trail.
        entries = AuditEntry.objects.filter(
            junction=self.junction,
            event_type='CONTROLLER_FAILURE',
            command_id='cmd-mismatch-1',
        )
        self.assertTrue(entries.exists())
        self.assertFalse(entries.latest('id').details['signals_match'])

        # Actual signals must NOT have been updated to the controller's claim.
        status = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status.data['actual_signals']['NORTH'], 'GREEN')
        self.assertEqual(status.data['controller_status'], 'WARNING')

    def test_ack_without_actual_state_trusts_requested(self):
        """ACK with no actual_signals body confirms the requested signals."""
        cmd = ControllerCommand.objects.create(
            command_id='cmd-no-state-1',
            junction=self.junction,
            requested_signals={
                'NORTH': 'GREEN', 'SOUTH': 'GREEN',
                'EAST': 'RED', 'WEST': 'RED'
            },
            status='PENDING',
        )
        response = self.client.post('/api/controller-events/', {
            'command_id': 'cmd-no-state-1',
            'junction_id': 'A',
            'status': 'ACK',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        cmd.refresh_from_db()
        self.assertEqual(cmd.status, 'ACKNOWLEDGED')


class AuditHistoryAPITest(TestCase):
    """Tests for audit history endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.client.post('/api/junctions/', {
            'junction_id': 'A', 'name': 'J-A'
        }, format='json')

    def test_history_recorded(self):
        """Events create audit entries retrievable via history API."""
        # Create some events
        self.client.post('/api/sensor-events/', {
            'event_id': 'evt-h1',
            'junction_id': 'A',
            'direction': 'NORTH',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-1',
            'vehicle_type': 'TRUCK',
        }, format='json')

        response = self.client.get('/api/junctions/A/history/')
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.data['count'], 0)

    def test_history_limit(self):
        """History respects limit parameter."""
        response = self.client.get('/api/junctions/A/history/?limit=5')
        self.assertEqual(response.status_code, 200)

    def test_unknown_junction_history(self):
        """History for unknown junction returns 404."""
        response = self.client.get('/api/junctions/UNKNOWN/history/')
        self.assertEqual(response.status_code, 404)


class ConcurrencyAPITest(TransactionTestCase):
    """Tests for concurrent operations."""

    def setUp(self):
        self.client = APIClient()
        self.client.post('/api/junctions/', {
            'junction_id': 'A', 'name': 'J-A'
        }, format='json')

    def test_concurrent_duplicate_events(self):
        """Concurrent duplicate events should not create duplicate queue entries."""
        import threading

        results = []
        event_data = {
            'event_id': 'evt-conc-1',
            'junction_id': 'A',
            'direction': 'NORTH',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-CONC',
            'vehicle_type': 'TRUCK',
        }

        def submit():
            client = APIClient()
            r = client.post('/api/sensor-events/', event_data, format='json')
            results.append(r.status_code)

        threads = [threading.Thread(target=submit) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one vehicle in queue
        count = WaitingVehicle.objects.filter(
            junction__junction_id='A', vehicle_id='VH-CONC'
        ).count()
        self.assertEqual(count, 1)

        # At most one 201, rest should be 200 (duplicate)
        self.assertLessEqual(results.count(201), 1)

    def test_concurrent_duplicate_event_different_payload(self):
        """Same event_id with different payloads: only one queue mutation."""
        import threading

        results = []
        base_event = {
            'event_id': 'evt-conc-diff-payload',
            'junction_id': 'A',
            'direction': 'NORTH',
            'event_type': 'VEHICLE_ARRIVED',
            'sequence_no': 9001,
        }

        def submit(vehicle_id, vehicle_type):
            client = APIClient()
            data = dict(base_event, vehicle_id=vehicle_id, vehicle_type=vehicle_type)
            r = client.post('/api/sensor-events/', data, format='json')
            results.append(r)

        threads = [
            threading.Thread(target=submit, args=('VH-RACE-1', 'TRUCK')),
            threading.Thread(target=submit, args=('VH-RACE-2', 'FORKLIFT')),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one of the two vehicles may be enqueued for this event_id
        count = WaitingVehicle.objects.filter(junction__junction_id='A').count()
        self.assertEqual(count, 1)

        # One submission is accepted (201), the other is a duplicate (200)
        statuses = sorted([r.status_code for r in results])
        self.assertEqual(statuses, [200, 201])

        # The duplicate must report the original event as already processed
        duplicates = [r for r in results if r.status_code == 200]
        self.assertEqual(duplicates[0].data['status'], 'DUPLICATE')

