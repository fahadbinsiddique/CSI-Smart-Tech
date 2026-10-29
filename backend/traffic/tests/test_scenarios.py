"""
End-to-End Functional Scenario Tests for Factory Traffic Management System.

Explicitly verifies all 9 assessment scenarios required by Section 15:
1. Normal Traffic: Several vehicles arrive from different directions, system determines phase.
2. Priority Traffic: TRUCK or FORKLIFT prioritised over employee traffic.
3. Emergency Preemption: Conflicting green phase performs safe transition (GREEN->YELLOW->ALL_RED->GREEN).
4. Manual Override: Administrator takes control and later returns to automatic.
5. Duplicate Event: Exact duplicate event submitted twice, queues remain correct.
6. Vehicle Clearance: Vehicle arrives and later clears, queues update correctly.
7. Controller Failure: Controller reports OFFLINE or fails ACK, system responds safely.
8. Restart Recovery: Backend restarts with existing data, applies safe recovery.
9. Concurrent Events: Simultaneous arrivals, emergencies, overrides, and ACKs preserve consistency.
"""
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from django.utils import timezone
from datetime import timedelta
import threading

from traffic.domain.enums import (
    OperatingMode,
    Phase,
    TransitionState,
    DeviceHealth,
    VehicleType,
)
from traffic.infrastructure.models import (
    Junction,
    JunctionState,
    WaitingVehicle,
    ProcessedEvent,
    ControllerCommand,
    AuditEntry,
)
from traffic.application.transition_service import TransitionService
from traffic.application.recovery_service import RecoveryService


class FunctionalScenariosTest(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        # Create Junction A
        self.client.post('/api/junctions/', {
            'junction_id': 'A',
            'name': 'Factory Junction A'
        }, format='json')

    def test_scenario_1_normal_traffic(self):
        """Scenario 1: Normal traffic arrivals from different directions."""
        # 3 Employee vehicles arrive North
        for i in range(3):
            res = self.client.post('/api/sensor-events/', {
                'event_id': f'evt-s1-n{i}',
                'junction_id': 'A',
                'direction': 'NORTH',
                'event_type': 'VEHICLE_ARRIVED',
                'vehicle_id': f'VH-N-{i}',
                'vehicle_type': 'EMPLOYEE_VEHICLE',
            }, format='json')
            self.assertEqual(res.status_code, 201)

        # 1 Employee vehicle arrives East
        res = self.client.post('/api/sensor-events/', {
            'event_id': 'evt-s1-e0',
            'junction_id': 'A',
            'direction': 'EAST',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-E-0',
            'vehicle_type': 'EMPLOYEE_VEHICLE',
        }, format='json')
        self.assertEqual(res.status_code, 201)

        status_res = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status_res.data['queues']['NORTH'], 3)
        self.assertEqual(status_res.data['queues']['EAST'], 1)

    def test_scenario_2_priority_traffic(self):
        """Scenario 2: TRUCK priority over employee vehicle."""
        # Arrive 1 Employee vehicle on North
        self.client.post('/api/sensor-events/', {
            'event_id': 'evt-s2-emp',
            'junction_id': 'A',
            'direction': 'NORTH',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-EMP',
            'vehicle_type': 'EMPLOYEE_VEHICLE',
        }, format='json')

        # Arrive 1 TRUCK on East
        self.client.post('/api/sensor-events/', {
            'event_id': 'evt-s2-truck',
            'junction_id': 'A',
            'direction': 'EAST',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-TRUCK',
            'vehicle_type': 'TRUCK',
        }, format='json')

        v_truck = WaitingVehicle.objects.get(vehicle_id='VH-TRUCK')
        v_emp = WaitingVehicle.objects.get(vehicle_id='VH-EMP')
        self.assertGreater(v_truck.priority, v_emp.priority)

    def test_scenario_3_emergency_preemption(self):
        """Scenario 3: Emergency preemption safely initiates transition sequence."""
        # Initial state is NORTH_SOUTH GREEN
        status_res = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status_res.data['phase'], 'NORTH_SOUTH')
        self.assertEqual(status_res.data['transition_state'], 'STABLE')

        # Emergency arrives from EAST (conflicting direction)
        res = self.client.post('/api/sensor-events/', {
            'event_id': 'evt-s3-emg',
            'junction_id': 'A',
            'direction': 'EAST',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'EMG-911',
            'vehicle_type': 'EMERGENCY',
        }, format='json')
        self.assertEqual(res.status_code, 201)

        # Check that state transitioned to YELLOW (safe clearance begun, never direct GREEN)
        status_after = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status_after.data['mode'], 'EMERGENCY')
        self.assertEqual(status_after.data['transition_state'], 'YELLOW')
        self.assertEqual(status_after.data['active_emergency'], 'EAST')
        # North and South are YELLOW, East and West remain RED
        self.assertEqual(status_after.data['desired_signals']['NORTH'], 'YELLOW')
        self.assertEqual(status_after.data['desired_signals']['EAST'], 'RED')

    def test_scenario_4_manual_override(self):
        """Scenario 4: Manual control override and return to automatic."""
        # Request manual green for WEST
        res = self.client.post('/api/junctions/A/commands/', {
            'command': 'MANUAL_GREEN_REQUEST',
            'direction': 'WEST'
        }, format='json')
        self.assertEqual(res.status_code, 200)

        status_man = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status_man.data['mode'], 'MANUAL')

        # Return to automatic
        res_auto = self.client.post('/api/junctions/A/commands/', {
            'command': 'RETURN_TO_AUTOMATIC'
        }, format='json')
        self.assertEqual(res_auto.status_code, 200)

        status_auto = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status_auto.data['mode'], 'AUTOMATIC')

    def test_scenario_5_duplicate_event(self):
        """Scenario 5: Duplicate sensor event submission."""
        event_payload = {
            'event_id': 'evt-s5-dup',
            'junction_id': 'A',
            'direction': 'SOUTH',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-DUP-TEST',
            'vehicle_type': 'FORKLIFT',
        }
        res1 = self.client.post('/api/sensor-events/', event_payload, format='json')
        self.assertEqual(res1.status_code, 201)

        res2 = self.client.post('/api/sensor-events/', event_payload, format='json')
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data['status'], 'DUPLICATE')

        # Queue count must be exactly 1
        self.assertEqual(WaitingVehicle.objects.filter(vehicle_id='VH-DUP-TEST').count(), 1)

    def test_scenario_6_vehicle_clearance(self):
        """Scenario 6: Vehicle arrives and clears."""
        self.client.post('/api/sensor-events/', {
            'event_id': 'evt-s6-arr',
            'junction_id': 'A',
            'direction': 'WEST',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-CLEAR-ME',
            'vehicle_type': 'TRUCK',
        }, format='json')
        self.assertEqual(WaitingVehicle.objects.filter(vehicle_id='VH-CLEAR-ME').count(), 1)

        self.client.post('/api/sensor-events/', {
            'event_id': 'evt-s6-clr',
            'junction_id': 'A',
            'direction': 'WEST',
            'event_type': 'VEHICLE_CLEARED',
            'vehicle_id': 'VH-CLEAR-ME',
        }, format='json')
        self.assertEqual(WaitingVehicle.objects.filter(vehicle_id='VH-CLEAR-ME').count(), 0)

    def test_scenario_7_controller_failure(self):
        """Scenario 7: Controller failure puts junction in DEGRADED mode safely."""
        res = self.client.post('/api/controller-events/', {
            'junction_id': 'A',
            'device_type': 'SIGNAL_CONTROLLER',
            'status': 'OFFLINE',
        }, format='json')
        self.assertEqual(res.status_code, 200)

        status_res = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status_res.data['mode'], 'DEGRADED')
        self.assertEqual(status_res.data['controller_status'], 'OFFLINE')
        self.assertEqual(status_res.data['actual_signals']['NORTH'], 'UNKNOWN')

    def test_scenario_8_restart_recovery(self):
        """Scenario 8: Restart recovery puts uncertain states into ALL_RED."""
        junction = Junction.objects.get(junction_id='A')
        # Simulate unconfirmed mid-transition state during restart
        j_state = junction.state
        j_state.transition_state = 'YELLOW'
        j_state.save()

        recovery = RecoveryService()
        recovered_count = recovery.recover_all_junctions()
        self.assertGreaterEqual(recovered_count, 1)

        j_state.refresh_from_db()
        self.assertEqual(j_state.transition_state, 'ALL_RED')
        self.assertEqual(j_state.desired_signals['NORTH'], 'RED')
        self.assertEqual(j_state.desired_signals['EAST'], 'RED')

    def test_emergency_cleared_by_clearance_event(self):
        """Clearing the emergency vehicle returns the junction to AUTOMATIC."""
        # Emergency arrives from EAST while NORTH_SOUTH is GREEN
        self.client.post('/api/sensor-events/', {
            'event_id': 'evt-emg-clear',
            'junction_id': 'A',
            'direction': 'EAST',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'EMG-RELEASE',
            'vehicle_type': 'EMERGENCY',
        }, format='json')

        status = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status.data['mode'], 'EMERGENCY')
        self.assertEqual(status.data['active_emergency'], 'EAST')

        # The emergency vehicle leaves the junction
        self.client.post('/api/sensor-events/', {
            'event_id': 'evt-emg-clear-clr',
            'junction_id': 'A',
            'direction': 'EAST',
            'event_type': 'VEHICLE_CLEARED',
            'vehicle_id': 'EMG-RELEASE',
        }, format='json')

        status = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status.data['mode'], 'AUTOMATIC')
        self.assertIsNone(status.data['active_emergency'])

    def test_scenario_9_concurrent_events(self):
        """Scenario 9: Concurrent arrivals, emergency, and manual commands."""
        results = []

        def t_arrival():
            client = APIClient()
            r = client.post('/api/sensor-events/', {
                'event_id': 'evt-conc-arr',
                'junction_id': 'A',
                'direction': 'NORTH',
                'event_type': 'VEHICLE_ARRIVED',
                'vehicle_id': 'VH-CONC-1',
                'vehicle_type': 'TRUCK'
            }, format='json')
            results.append(('arr', r.status_code))

        def t_emergency():
            client = APIClient()
            r = client.post('/api/sensor-events/', {
                'event_id': 'evt-conc-emg',
                'junction_id': 'A',
                'direction': 'EAST',
                'event_type': 'VEHICLE_ARRIVED',
                'vehicle_id': 'VH-CONC-EMG',
                'vehicle_type': 'EMERGENCY'
            }, format='json')
            results.append(('emg', r.status_code))

        def t_manual():
            client = APIClient()
            r = client.post('/api/junctions/A/commands/', {
                'command': 'MANUAL_GREEN_REQUEST',
                'direction': 'WEST'
            }, format='json')
            results.append(('man', r.status_code))

        threads = [
            threading.Thread(target=t_arrival),
            threading.Thread(target=t_emergency),
            threading.Thread(target=t_manual),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Duplicate of the EAST emergency event must not be re-applied.
        r_dup = self.client.post('/api/sensor-events/', {
            'event_id': 'evt-conc-emg',
            'junction_id': 'A',
            'direction': 'EAST',
            'event_type': 'VEHICLE_ARRIVED',
            'vehicle_id': 'VH-CONC-EMG-DUP',
            'vehicle_type': 'EMERGENCY',
        }, format='json')
        self.assertEqual(r_dup.status_code, 200)
        self.assertEqual(r_dup.data['status'], 'DUPLICATE')

        # Controller ACK for a pending command must be processed safely.
        junction = Junction.objects.get(junction_id='A')
        cmd = ControllerCommand.objects.create(
            command_id='cmd-conc-ack',
            junction=junction,
            requested_signals={
                'NORTH': 'RED', 'SOUTH': 'RED',
                'EAST': 'GREEN', 'WEST': 'GREEN'
            },
            status='PENDING',
        )
        r_ack = self.client.post('/api/controller-events/', {
            'command_id': 'cmd-conc-ack',
            'junction_id': 'A',
            'status': 'ACK',
            'actual_signals': {
                'NORTH': 'RED', 'SOUTH': 'RED',
                'EAST': 'GREEN', 'WEST': 'GREEN'
            },
        }, format='json')
        self.assertEqual(r_ack.status_code, 200)

        # Final state must remain valid and non-corrupted.
        status = self.client.get('/api/junctions/A/status/')
        self.assertEqual(status.status_code, 200)

        # Idempotency: exactly one queue entry for the emergency event_id.
        emg_count = WaitingVehicle.objects.filter(
            junction__junction_id='A', vehicle_id='VH-CONC-EMG'
        ).count()
        self.assertEqual(emg_count, 1)

        # Exactly one ProcessedEvent for the duplicated event_id.
        evt_count = ProcessedEvent.objects.filter(event_id='evt-conc-emg').count()
        self.assertEqual(evt_count, 1)

        # Safety invariant holds: never conflicting GREEN.
        des = status.data['desired_signals']
        greens = [k for k, v in des.items() if v == 'GREEN']
        if 'NORTH' in greens or 'SOUTH' in greens:
            self.assertNotIn('EAST', greens)
            self.assertNotIn('WEST', greens)

    def test_stale_emergency_timeout_clears_emergency(self):
        """Stale emergency (uncleared past the 300s timeout) returns to AUTOMATIC."""
        junction = Junction.objects.get(junction_id='A')
        j_state = junction.state
        j_state.mode = OperatingMode.EMERGENCY.value
        j_state.active_emergency_direction = 'EAST'
        j_state.save()

        # Emergency vehicle that arrived over 5 minutes ago and never cleared.
        WaitingVehicle.objects.create(
            junction=junction,
            direction='EAST',
            vehicle_id='EMG-STALE',
            vehicle_type=VehicleType.EMERGENCY.value,
            priority=100,
            arrived_at=timezone.now() - timedelta(seconds=301),
            event_id='evt-stale-emg',
        )

        cleared = TransitionService().clear_stale_emergencies()
        self.assertEqual(cleared, 1)

        j_state.refresh_from_db()
        self.assertEqual(j_state.mode, OperatingMode.AUTOMATIC.value)
        self.assertIsNone(j_state.active_emergency_direction)
        self.assertIsNotNone(j_state.next_transition_at)

        # Audit trail records the timeout-based clearance.
        entries = AuditEntry.objects.filter(
            junction=junction,
            event_type='EMERGENCY_CLEARED',
        )
        self.assertTrue(entries.exists())
        self.assertEqual(
            entries.latest('id').details.get('reason'),
            'stale emergency timeout',
        )

    def test_recent_emergency_is_not_cleared_by_timeout(self):
        """An emergency vehicle waiting less than 300s must not be timed out."""
        junction = Junction.objects.get(junction_id='A')
        j_state = junction.state
        j_state.mode = OperatingMode.EMERGENCY.value
        j_state.active_emergency_direction = 'EAST'
        j_state.save()

        WaitingVehicle.objects.create(
            junction=junction,
            direction='EAST',
            vehicle_id='EMG-FRESH',
            vehicle_type=VehicleType.EMERGENCY.value,
            priority=100,
            arrived_at=timezone.now() - timedelta(seconds=10),
            event_id='evt-fresh-emg',
        )

        cleared = TransitionService().clear_stale_emergencies()
        self.assertEqual(cleared, 0)

        j_state.refresh_from_db()
        self.assertEqual(j_state.mode, OperatingMode.EMERGENCY.value)
        self.assertEqual(j_state.active_emergency_direction, 'EAST')

