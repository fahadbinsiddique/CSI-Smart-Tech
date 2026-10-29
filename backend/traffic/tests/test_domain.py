"""
Domain unit tests for the Traffic State Machine.

These tests verify the core domain logic WITHOUT any Django dependencies.
They use FakeClock for deterministic time control.
"""
import unittest
from datetime import datetime, timedelta, timezone

from traffic.domain.clock import FakeClock
from traffic.domain.enums import (
    DeviceHealth,
    Direction,
    OperatingMode,
    Phase,
    SignalState,
    TransitionState,
    DEFAULT_GREEN_DURATION,
    YELLOW_DURATION,
    ALL_RED_DURATION,
)
from traffic.domain.exceptions import (
    InvalidCommandError,
    SafetyViolationError,
)
from traffic.domain.models import (
    JunctionStateSnapshot,
    SignalVector,
    WaitingVehicle,
)
from traffic.domain.safety import (
    get_opposing_phase,
    get_phase_for_direction,
    validate_no_conflicting_green,
    validate_transition_sequence,
)
from traffic.domain.state_machine import TrafficStateMachine


def make_state(
    phase=Phase.NORTH_SOUTH,
    transition_state=TransitionState.STABLE,
    mode=OperatingMode.AUTOMATIC,
    controller_health=DeviceHealth.ONLINE,
    desired_signals=None,
    actual_signals=None,
    next_transition_at=None,
    version=1,
    active_emergency_direction=None,
    manual_direction=None,
    queues=None,
    waiting_vehicles=None,
    phase_started_at=None,
):
    """Helper to create a JunctionStateSnapshot for testing."""
    if desired_signals is None:
        desired_signals = SignalVector.for_phase(phase)
    if actual_signals is None:
        actual_signals = desired_signals
    if queues is None:
        queues = {d: 0 for d in Direction}
    if waiting_vehicles is None:
        waiting_vehicles = {d: [] for d in Direction}
    return JunctionStateSnapshot(
        junction_id="A",
        mode=mode,
        current_phase=phase,
        transition_state=transition_state,
        desired_signals=desired_signals,
        actual_signals=actual_signals,
        controller_health=controller_health,
        active_emergency_direction=active_emergency_direction,
        next_transition_at=next_transition_at,
        version=version,
        queues=queues,
        waiting_vehicles=waiting_vehicles,
        phase_started_at=phase_started_at,
        manual_direction=manual_direction,
    )


class TestSignalVector(unittest.TestCase):
    """Tests for the SignalVector value object."""

    def test_all_red(self):
        sv = SignalVector.all_red()
        self.assertEqual(sv.north, SignalState.RED)
        self.assertEqual(sv.south, SignalState.RED)
        self.assertEqual(sv.east, SignalState.RED)
        self.assertEqual(sv.west, SignalState.RED)

    def test_for_phase_north_south(self):
        sv = SignalVector.for_phase(Phase.NORTH_SOUTH)
        self.assertEqual(sv.north, SignalState.GREEN)
        self.assertEqual(sv.south, SignalState.GREEN)
        self.assertEqual(sv.east, SignalState.RED)
        self.assertEqual(sv.west, SignalState.RED)

    def test_for_phase_east_west(self):
        sv = SignalVector.for_phase(Phase.EAST_WEST)
        self.assertEqual(sv.north, SignalState.RED)
        self.assertEqual(sv.south, SignalState.RED)
        self.assertEqual(sv.east, SignalState.GREEN)
        self.assertEqual(sv.west, SignalState.GREEN)

    def test_yellow_for_phase(self):
        sv = SignalVector.yellow_for_phase(Phase.NORTH_SOUTH)
        self.assertEqual(sv.north, SignalState.YELLOW)
        self.assertEqual(sv.south, SignalState.YELLOW)
        self.assertEqual(sv.east, SignalState.RED)
        self.assertEqual(sv.west, SignalState.RED)

    def test_has_conflicting_green_false(self):
        sv = SignalVector.for_phase(Phase.NORTH_SOUTH)
        self.assertFalse(sv.has_conflicting_green())

    def test_has_conflicting_green_true(self):
        sv = SignalVector(
            north=SignalState.GREEN,
            south=SignalState.RED,
            east=SignalState.GREEN,
            west=SignalState.RED,
        )
        self.assertTrue(sv.has_conflicting_green())

    def test_round_trip_dict(self):
        sv = SignalVector.for_phase(Phase.EAST_WEST)
        d = sv.as_dict()
        sv2 = SignalVector.from_dict(d)
        self.assertEqual(sv, sv2)


class TestSafetyInvariants(unittest.TestCase):
    """Tests for safety invariant checks."""

    def test_valid_north_south_green(self):
        sv = SignalVector.for_phase(Phase.NORTH_SOUTH)
        validate_no_conflicting_green(sv)  # Should not raise

    def test_conflicting_green_raises(self):
        sv = SignalVector(
            north=SignalState.GREEN,
            south=SignalState.RED,
            east=SignalState.GREEN,
            west=SignalState.RED,
        )
        with self.assertRaises(SafetyViolationError):
            validate_no_conflicting_green(sv)

    def test_all_red_is_safe(self):
        sv = SignalVector.all_red()
        validate_no_conflicting_green(sv)  # Should not raise

    def test_direct_green_to_green_forbidden(self):
        current = SignalVector.for_phase(Phase.NORTH_SOUTH)
        proposed = SignalVector.for_phase(Phase.EAST_WEST)
        with self.assertRaises(SafetyViolationError):
            validate_transition_sequence(current, proposed)

    def test_green_to_yellow_allowed(self):
        current = SignalVector.for_phase(Phase.NORTH_SOUTH)
        proposed = SignalVector.yellow_for_phase(Phase.NORTH_SOUTH)
        validate_transition_sequence(current, proposed)  # Should not raise

    def test_get_phase_for_direction(self):
        self.assertEqual(get_phase_for_direction(Direction.NORTH), Phase.NORTH_SOUTH)
        self.assertEqual(get_phase_for_direction(Direction.EAST), Phase.EAST_WEST)

    def test_get_opposing_phase(self):
        self.assertEqual(get_opposing_phase(Phase.NORTH_SOUTH), Phase.EAST_WEST)
        self.assertEqual(get_opposing_phase(Phase.EAST_WEST), Phase.NORTH_SOUTH)


class TestStateMachineTransitions(unittest.TestCase):
    """Tests for the traffic state machine transition logic."""

    def setUp(self):
        self.clock = FakeClock()
        self.sm = TrafficStateMachine(self.clock)

    def test_stable_to_yellow_on_due_transition(self):
        """GREEN → YELLOW when transition is due."""
        now = self.clock.now()
        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.STABLE,
            next_transition_at=now - timedelta(seconds=1),  # Due
        )
        result = self.sm.process_due_transition(state)
        self.assertIsNotNone(result)
        self.assertEqual(result.new_transition_state, TransitionState.YELLOW)
        # Desired signals should be YELLOW for NORTH/SOUTH
        self.assertEqual(
            result.new_desired_signals,
            SignalVector.yellow_for_phase(Phase.NORTH_SOUTH),
        )

    def test_yellow_to_all_red(self):
        """YELLOW → ALL_RED when transition is due."""
        now = self.clock.now()
        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.YELLOW,
            desired_signals=SignalVector.yellow_for_phase(Phase.NORTH_SOUTH),
            next_transition_at=now - timedelta(seconds=1),
        )
        result = self.sm.process_due_transition(state)
        self.assertIsNotNone(result)
        self.assertEqual(result.new_transition_state, TransitionState.ALL_RED)
        self.assertEqual(result.new_desired_signals, SignalVector.all_red())

    def test_all_red_to_green(self):
        """ALL_RED → GREEN (next phase) when transition is due."""
        now = self.clock.now()
        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.ALL_RED,
            desired_signals=SignalVector.all_red(),
            next_transition_at=now - timedelta(seconds=1),
        )
        result = self.sm.process_due_transition(state)
        self.assertIsNotNone(result)
        self.assertEqual(result.new_transition_state, TransitionState.STABLE)
        # Should switch to opposing phase
        self.assertEqual(result.new_phase, Phase.EAST_WEST)
        self.assertEqual(
            result.new_desired_signals,
            SignalVector.for_phase(Phase.EAST_WEST),
        )
        self.assertTrue(result.phase_changed)

    def test_full_transition_cycle(self):
        """Complete cycle: GREEN → YELLOW → ALL_RED → GREEN."""
        now = self.clock.now()

        # Step 1: STABLE → YELLOW
        state1 = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.STABLE,
            next_transition_at=now,
        )
        r1 = self.sm.process_due_transition(state1)
        self.assertEqual(r1.new_transition_state, TransitionState.YELLOW)

        # Step 2: YELLOW → ALL_RED
        self.clock.advance(YELLOW_DURATION)
        state2 = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.YELLOW,
            desired_signals=r1.new_desired_signals,
            next_transition_at=r1.next_transition_at,
        )
        r2 = self.sm.process_due_transition(state2)
        self.assertEqual(r2.new_transition_state, TransitionState.ALL_RED)

        # Step 3: ALL_RED → GREEN (EAST_WEST)
        self.clock.advance(ALL_RED_DURATION)
        state3 = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.ALL_RED,
            desired_signals=r2.new_desired_signals,
            next_transition_at=r2.next_transition_at,
        )
        r3 = self.sm.process_due_transition(state3)
        self.assertEqual(r3.new_transition_state, TransitionState.STABLE)
        self.assertEqual(r3.new_phase, Phase.EAST_WEST)

        # Verify safety: no conflicting GREEN in final signals
        validate_no_conflicting_green(r3.new_desired_signals)

    def test_not_due_returns_none(self):
        """No transition when deadline hasn't passed."""
        now = self.clock.now()
        state = make_state(
            next_transition_at=now + timedelta(seconds=10),
        )
        result = self.sm.process_due_transition(state)
        self.assertIsNone(result)

    def test_no_transition_in_degraded_mode(self):
        """No transitions in DEGRADED mode."""
        now = self.clock.now()
        state = make_state(
            mode=OperatingMode.DEGRADED,
            next_transition_at=now - timedelta(seconds=1),
        )
        result = self.sm.process_due_transition(state)
        self.assertIsNone(result)

    def test_no_transition_without_deadline(self):
        """No transition when no deadline is set."""
        state = make_state(next_transition_at=None)
        result = self.sm.process_due_transition(state)
        self.assertIsNone(result)

    def test_green_duration_sets_correct_deadline(self):
        """ALL_RED → GREEN sets the correct next_transition_at deadline in AUTOMATIC mode."""
        now = self.clock.now()
        state = make_state(
            transition_state=TransitionState.ALL_RED,
            desired_signals=SignalVector.all_red(),
            next_transition_at=now,
        )
        result = self.sm.process_due_transition(state)
        expected_deadline = now + timedelta(seconds=DEFAULT_GREEN_DURATION)
        self.assertEqual(result.next_transition_at, expected_deadline)

    def test_green_transition_in_manual_mode_has_no_automatic_deadline(self):
        """ALL_RED → GREEN in MANUAL mode holds GREEN indefinitely without automatic deadline."""
        now = self.clock.now()
        state = make_state(
            mode=OperatingMode.MANUAL,
            transition_state=TransitionState.ALL_RED,
            desired_signals=SignalVector.all_red(),
            next_transition_at=now,
            manual_direction=Direction.EAST,
        )
        result = self.sm.process_due_transition(state)
        self.assertEqual(result.new_mode, OperatingMode.MANUAL)
        self.assertEqual(result.new_transition_state, TransitionState.STABLE)
        self.assertIsNone(result.next_transition_at)

    def test_green_transition_in_emergency_mode_has_no_automatic_deadline(self):
        """ALL_RED → GREEN in EMERGENCY mode holds GREEN until explicitly cleared."""
        now = self.clock.now()
        state = make_state(
            mode=OperatingMode.EMERGENCY,
            transition_state=TransitionState.ALL_RED,
            desired_signals=SignalVector.all_red(),
            next_transition_at=now,
            active_emergency_direction=Direction.EAST,
        )
        result = self.sm.process_due_transition(state)
        self.assertEqual(result.new_mode, OperatingMode.EMERGENCY)
        self.assertEqual(result.new_transition_state, TransitionState.STABLE)
        self.assertIsNone(result.next_transition_at)


class TestEmergencyPreemption(unittest.TestCase):
    """Tests for emergency preemption logic."""

    def setUp(self):
        self.clock = FakeClock()
        self.sm = TrafficStateMachine(self.clock)

    def test_emergency_same_phase_no_transition(self):
        """Emergency from same phase direction → no transition, just mode change."""
        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.STABLE,
        )
        result = self.sm.initiate_emergency_preemption(state, Direction.NORTH)
        self.assertIsNotNone(result)
        self.assertEqual(result.new_mode, OperatingMode.EMERGENCY)
        self.assertEqual(result.new_transition_state, TransitionState.STABLE)
        self.assertFalse(result.phase_changed)

    def test_emergency_conflicting_phase_starts_yellow(self):
        """Emergency from conflicting phase → start YELLOW transition."""
        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.STABLE,
        )
        result = self.sm.initiate_emergency_preemption(state, Direction.EAST)
        self.assertIsNotNone(result)
        self.assertEqual(result.new_mode, OperatingMode.EMERGENCY)
        self.assertEqual(result.new_transition_state, TransitionState.YELLOW)
        # Must go through YELLOW → ALL_RED → GREEN, never direct GREEN
        self.assertEqual(
            result.new_desired_signals,
            SignalVector.yellow_for_phase(Phase.NORTH_SOUTH),
        )

    def test_emergency_during_transition_keeps_mode(self):
        """Emergency during ongoing transition just updates mode."""
        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.YELLOW,
            desired_signals=SignalVector.yellow_for_phase(Phase.NORTH_SOUTH),
        )
        result = self.sm.initiate_emergency_preemption(state, Direction.EAST)
        self.assertEqual(result.new_mode, OperatingMode.EMERGENCY)
        self.assertEqual(result.new_transition_state, TransitionState.YELLOW)

    def test_emergency_never_bypasses_safety(self):
        """Emergency transition must never produce conflicting GREEN."""
        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.STABLE,
        )
        result = self.sm.initiate_emergency_preemption(state, Direction.EAST)
        # Must not immediately jump to GREEN for conflicting phase
        self.assertNotEqual(
            result.new_desired_signals,
            SignalVector.for_phase(Phase.EAST_WEST),
        )


class TestManualControl(unittest.TestCase):
    """Tests for manual control logic."""

    def setUp(self):
        self.clock = FakeClock()
        self.sm = TrafficStateMachine(self.clock)

    def test_manual_green_same_phase(self):
        """Manual GREEN for direction in current phase → just switch mode."""
        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.STABLE,
        )
        result = self.sm.initiate_manual_green(state, Direction.NORTH)
        self.assertEqual(result.new_mode, OperatingMode.MANUAL)
        self.assertEqual(result.new_transition_state, TransitionState.STABLE)
        # Manual mode: no automatic transition
        self.assertIsNone(result.next_transition_at)

    def test_manual_green_conflicting_phase_starts_transition(self):
        """Manual GREEN for conflicting phase → start YELLOW."""
        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.STABLE,
        )
        result = self.sm.initiate_manual_green(state, Direction.EAST)
        self.assertEqual(result.new_mode, OperatingMode.MANUAL)
        self.assertEqual(result.new_transition_state, TransitionState.YELLOW)

    def test_manual_during_transition_rejected(self):
        """Manual command during transition → rejected."""
        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.YELLOW,
            desired_signals=SignalVector.yellow_for_phase(Phase.NORTH_SOUTH),
        )
        with self.assertRaises(InvalidCommandError):
            self.sm.initiate_manual_green(state, Direction.EAST)

    def test_manual_during_degraded_rejected(self):
        """Manual command during DEGRADED mode → rejected."""
        state = make_state(mode=OperatingMode.DEGRADED)
        with self.assertRaises(InvalidCommandError):
            self.sm.initiate_manual_green(state, Direction.EAST)

    def test_manual_during_emergency_rejected(self):
        """Manual command during EMERGENCY → rejected."""
        state = make_state(mode=OperatingMode.EMERGENCY)
        with self.assertRaises(InvalidCommandError):
            self.sm.initiate_manual_green(state, Direction.EAST)

    def test_return_to_automatic(self):
        """Return to automatic mode."""
        state = make_state(mode=OperatingMode.MANUAL)
        result = self.sm.return_to_automatic(state)
        self.assertEqual(result.new_mode, OperatingMode.AUTOMATIC)
        self.assertIsNotNone(result.next_transition_at)

    def test_manual_uses_safe_transition(self):
        """Manual GREEN uses same safe transition as automatic."""
        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.STABLE,
        )
        result = self.sm.initiate_manual_green(state, Direction.WEST)
        # Must not jump to conflicting GREEN directly
        self.assertNotEqual(
            result.new_desired_signals,
            SignalVector.for_phase(Phase.EAST_WEST),
        )
        self.assertEqual(result.new_transition_state, TransitionState.YELLOW)


class TestRecovery(unittest.TestCase):
    """Tests for restart recovery logic."""

    def setUp(self):
        self.clock = FakeClock()
        self.sm = TrafficStateMachine(self.clock)

    def test_recovery_unknown_controller_goes_degraded(self):
        """Unknown controller state → DEGRADED + ALL_RED."""
        state = make_state(
            controller_health=DeviceHealth.UNKNOWN,
        )
        result = self.sm.compute_recovery_state(state)
        self.assertEqual(result.new_mode, OperatingMode.DEGRADED)
        self.assertEqual(result.new_transition_state, TransitionState.ALL_RED)
        self.assertEqual(result.new_desired_signals, SignalVector.all_red())
        self.assertIsNone(result.next_transition_at)

    def test_recovery_offline_controller_goes_degraded(self):
        """Offline controller → DEGRADED + ALL_RED."""
        state = make_state(
            controller_health=DeviceHealth.OFFLINE,
        )
        result = self.sm.compute_recovery_state(state)
        self.assertEqual(result.new_mode, OperatingMode.DEGRADED)

    def test_recovery_mid_yellow_goes_all_red(self):
        """Recovery during YELLOW → ALL_RED."""
        state = make_state(
            transition_state=TransitionState.YELLOW,
        )
        result = self.sm.compute_recovery_state(state)
        self.assertEqual(result.new_transition_state, TransitionState.ALL_RED)
        self.assertEqual(result.new_desired_signals, SignalVector.all_red())

    def test_recovery_never_blindly_advances_to_green(self):
        """Recovery must never blindly advance to GREEN."""
        # Test with various uncertain states
        for ts in [TransitionState.YELLOW, TransitionState.TRANSITIONING]:
            state = make_state(transition_state=ts)
            result = self.sm.compute_recovery_state(state)
            # Should NOT be GREEN for any conflicting phase
            self.assertNotEqual(
                result.new_transition_state, TransitionState.STABLE,
                f"Recovery from {ts.value} should not go directly to STABLE/GREEN"
            )

    def test_recovery_stable_matching_resumes(self):
        """Recovery when STABLE and actual matches desired → resume."""
        sv = SignalVector.for_phase(Phase.NORTH_SOUTH)
        state = make_state(
            transition_state=TransitionState.STABLE,
            desired_signals=sv,
            actual_signals=sv,
        )
        result = self.sm.compute_recovery_state(state)
        self.assertEqual(result.new_mode, OperatingMode.AUTOMATIC)
        self.assertEqual(result.new_transition_state, TransitionState.STABLE)

    def test_recovery_stable_mismatch_goes_degraded(self):
        """Recovery when actual != desired → DEGRADED."""
        state = make_state(
            transition_state=TransitionState.STABLE,
            desired_signals=SignalVector.for_phase(Phase.NORTH_SOUTH),
            actual_signals=SignalVector.for_phase(Phase.EAST_WEST),
        )
        result = self.sm.compute_recovery_state(state)
        self.assertEqual(result.new_mode, OperatingMode.DEGRADED)


class TestDeterminism(unittest.TestCase):
    """Tests that domain decisions are deterministic."""

    def test_same_input_same_output(self):
        """Identical inputs produce identical results."""
        clock = FakeClock()
        sm = TrafficStateMachine(clock)
        now = clock.now()

        state = make_state(
            phase=Phase.NORTH_SOUTH,
            transition_state=TransitionState.STABLE,
            next_transition_at=now,
        )

        r1 = sm.process_due_transition(state)
        r2 = sm.process_due_transition(state)

        self.assertEqual(r1.new_transition_state, r2.new_transition_state)
        self.assertEqual(r1.new_desired_signals, r2.new_desired_signals)
        self.assertEqual(r1.next_transition_at, r2.next_transition_at)


if __name__ == '__main__':
    unittest.main()

