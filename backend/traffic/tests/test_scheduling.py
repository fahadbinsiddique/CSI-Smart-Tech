"""
Scheduling policy tests.
Pure domain tests — no Django dependencies.
"""
import unittest
from datetime import datetime, timedelta, timezone

from traffic.domain.clock import FakeClock
from traffic.domain.enums import (
    DeviceHealth,
    Direction,
    OperatingMode,
    Phase,
    TransitionState,
    VehicleType,
    VEHICLE_PRIORITY,
    STARVATION_THRESHOLD,
)
from traffic.domain.models import (
    JunctionStateSnapshot,
    SignalVector,
    WaitingVehicle,
)
from traffic.domain.scheduling import TrafficScheduler


def make_state_with_queues(
    queues=None,
    waiting_vehicles=None,
    phase=Phase.NORTH_SOUTH,
    clock=None,
):
    """Helper to create a state with specific queue configurations."""
    if queues is None:
        queues = {d: 0 for d in Direction}
    if waiting_vehicles is None:
        waiting_vehicles = {d: [] for d in Direction}

    return JunctionStateSnapshot(
        junction_id="A",
        mode=OperatingMode.AUTOMATIC,
        current_phase=phase,
        transition_state=TransitionState.STABLE,
        desired_signals=SignalVector.for_phase(phase),
        actual_signals=SignalVector.for_phase(phase),
        controller_health=DeviceHealth.ONLINE,
        active_emergency_direction=None,
        next_transition_at=None,
        version=1,
        queues=queues,
        waiting_vehicles=waiting_vehicles,
    )


class TestSchedulingPolicy(unittest.TestCase):
    """Tests for the traffic scheduling policy."""

    def setUp(self):
        self.clock = FakeClock()
        self.scheduler = TrafficScheduler(self.clock)

    def test_empty_queues_switch_for_alternation(self):
        """With empty queues, prefer opposing phase for alternation."""
        state = make_state_with_queues()
        decision = self.scheduler.evaluate(state)
        # Scores should be equal (both 0), so prefer opposing phase
        self.assertEqual(decision.recommended_phase, Phase.EAST_WEST)
        self.assertTrue(decision.should_switch)

    def test_heavier_queue_gets_priority(self):
        """Phase with more vehicles should get higher score."""
        now = self.clock.now()
        queues = {
            Direction.NORTH: 5,
            Direction.SOUTH: 3,
            Direction.EAST: 1,
            Direction.WEST: 0,
        }
        vehicles_ns = []
        for i in range(8):
            d = Direction.NORTH if i < 5 else Direction.SOUTH
            vehicles_ns.append(WaitingVehicle(
                vehicle_id=f"V-{i}",
                vehicle_type=VehicleType.EMPLOYEE_VEHICLE,
                direction=d,
                arrived_at=now,
                priority=VEHICLE_PRIORITY[VehicleType.EMPLOYEE_VEHICLE],
            ))
        vehicles_ew = [WaitingVehicle(
            vehicle_id="V-E1",
            vehicle_type=VehicleType.EMPLOYEE_VEHICLE,
            direction=Direction.EAST,
            arrived_at=now,
            priority=VEHICLE_PRIORITY[VehicleType.EMPLOYEE_VEHICLE],
        )]

        waiting = {
            Direction.NORTH: [v for v in vehicles_ns if v.direction == Direction.NORTH],
            Direction.SOUTH: [v for v in vehicles_ns if v.direction == Direction.SOUTH],
            Direction.EAST: vehicles_ew,
            Direction.WEST: [],
        }

        state = make_state_with_queues(
            queues=queues,
            waiting_vehicles=waiting,
            phase=Phase.EAST_WEST,
        )
        decision = self.scheduler.evaluate(state)
        self.assertEqual(decision.recommended_phase, Phase.NORTH_SOUTH)
        self.assertTrue(decision.should_switch)

    def test_emergency_vehicle_gets_highest_priority(self):
        """Emergency vehicle should heavily influence scheduling."""
        now = self.clock.now()
        queues = {
            Direction.NORTH: 2,
            Direction.SOUTH: 1,
            Direction.EAST: 1,
            Direction.WEST: 0,
        }
        # A few employee vehicles N/S vs one emergency E
        ns_vehicles = [
            WaitingVehicle(
                vehicle_id=f"V-{i}",
                vehicle_type=VehicleType.EMPLOYEE_VEHICLE,
                direction=Direction.NORTH if i < 2 else Direction.SOUTH,
                arrived_at=now,
                priority=VEHICLE_PRIORITY[VehicleType.EMPLOYEE_VEHICLE],
            )
            for i in range(3)
        ]
        ew_vehicles = [
            WaitingVehicle(
                vehicle_id="EMG-1",
                vehicle_type=VehicleType.EMERGENCY,
                direction=Direction.EAST,
                arrived_at=now,
                priority=VEHICLE_PRIORITY[VehicleType.EMERGENCY],
            )
        ]

        waiting = {
            Direction.NORTH: [v for v in ns_vehicles if v.direction == Direction.NORTH],
            Direction.SOUTH: [v for v in ns_vehicles if v.direction == Direction.SOUTH],
            Direction.EAST: ew_vehicles,
            Direction.WEST: [],
        }

        state = make_state_with_queues(
            queues=queues,
            waiting_vehicles=waiting,
            phase=Phase.NORTH_SOUTH,
        )
        decision = self.scheduler.evaluate(state)
        # Emergency priority (100×3=300) should outweigh employee vehicles (10×3×3=90)
        self.assertEqual(decision.recommended_phase, Phase.EAST_WEST)

    def test_starvation_prevention(self):
        """Long-waiting vehicles get starvation bonus."""
        now = self.clock.now()
        long_ago = now - timedelta(seconds=STARVATION_THRESHOLD + 10)

        queues = {
            Direction.NORTH: 10,
            Direction.SOUTH: 10,
            Direction.EAST: 1,
            Direction.WEST: 0,
        }

        # Many vehicles N/S arriving now
        ns_vehicles = [
            WaitingVehicle(
                vehicle_id=f"V-{i}",
                vehicle_type=VehicleType.EMPLOYEE_VEHICLE,
                direction=Direction.NORTH,
                arrived_at=now,
                priority=VEHICLE_PRIORITY[VehicleType.EMPLOYEE_VEHICLE],
            )
            for i in range(10)
        ]

        # One starving vehicle EAST
        ew_vehicles = [
            WaitingVehicle(
                vehicle_id="V-STARVED",
                vehicle_type=VehicleType.EMPLOYEE_VEHICLE,
                direction=Direction.EAST,
                arrived_at=long_ago,
                priority=VEHICLE_PRIORITY[VehicleType.EMPLOYEE_VEHICLE],
            )
        ]

        waiting = {
            Direction.NORTH: ns_vehicles,
            Direction.SOUTH: [],
            Direction.EAST: ew_vehicles,
            Direction.WEST: [],
        }

        state = make_state_with_queues(
            queues=queues,
            waiting_vehicles=waiting,
            phase=Phase.NORTH_SOUTH,
        )
        decision = self.scheduler.evaluate(state)
        # Starvation bonus should boost EAST_WEST score
        self.assertGreater(
            decision.scores[Phase.EAST_WEST],
            0,
            "Starving vehicle should contribute positive score"
        )

    def test_truck_priority_over_employee(self):
        """Trucks should get higher priority than employee vehicles."""
        now = self.clock.now()
        queues = {
            Direction.NORTH: 1,
            Direction.SOUTH: 0,
            Direction.EAST: 1,
            Direction.WEST: 0,
        }
        ns_vehicles = [
            WaitingVehicle(
                vehicle_id="TRUCK-1",
                vehicle_type=VehicleType.TRUCK,
                direction=Direction.NORTH,
                arrived_at=now,
                priority=VEHICLE_PRIORITY[VehicleType.TRUCK],
            )
        ]
        ew_vehicles = [
            WaitingVehicle(
                vehicle_id="EMP-1",
                vehicle_type=VehicleType.EMPLOYEE_VEHICLE,
                direction=Direction.EAST,
                arrived_at=now,
                priority=VEHICLE_PRIORITY[VehicleType.EMPLOYEE_VEHICLE],
            )
        ]

        waiting = {
            Direction.NORTH: ns_vehicles,
            Direction.SOUTH: [],
            Direction.EAST: ew_vehicles,
            Direction.WEST: [],
        }

        state = make_state_with_queues(
            queues=queues,
            waiting_vehicles=waiting,
            phase=Phase.EAST_WEST,
        )
        decision = self.scheduler.evaluate(state)
        self.assertGreater(
            decision.scores[Phase.NORTH_SOUTH],
            decision.scores[Phase.EAST_WEST],
        )

    def test_deterministic_decisions(self):
        """Same state produces same scheduling decision."""
        now = self.clock.now()
        queues = {
            Direction.NORTH: 3,
            Direction.SOUTH: 2,
            Direction.EAST: 4,
            Direction.WEST: 1,
        }
        state = make_state_with_queues(queues=queues)

        d1 = self.scheduler.evaluate(state)
        d2 = self.scheduler.evaluate(state)

        self.assertEqual(d1.recommended_phase, d2.recommended_phase)
        self.assertEqual(d1.scores, d2.scores)
        self.assertEqual(d1.should_switch, d2.should_switch)


if __name__ == '__main__':
    unittest.main()
