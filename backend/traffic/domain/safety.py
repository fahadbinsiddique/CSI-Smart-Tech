"""
Safety invariant checks for the Factory Traffic Management System.
Pure Python — no framework dependencies.

These functions verify that traffic-safety invariants hold.
They are used both for validation and as assertions in the state machine.
"""
from typing import Dict, FrozenSet, Set

from .enums import (
    Direction,
    Phase,
    SignalState,
    CONFLICTING_PHASES,
    PHASE_DIRECTIONS,
)
from .models import SignalVector
from .exceptions import SafetyViolationError


def validate_no_conflicting_green(signal_vector: SignalVector) -> None:
    """
    Ensure no two directions from conflicting phases are simultaneously GREEN.
    
    Raises SafetyViolationError if a conflict is detected.
    """
    if signal_vector.has_conflicting_green():
        greens = signal_vector.green_directions()
        raise SafetyViolationError(
            f"Conflicting GREEN signals detected: {[d.value for d in greens]}. "
            f"Directions from conflicting phases must never be GREEN simultaneously."
        )


def validate_transition_sequence(
    current_signals: SignalVector,
    proposed_signals: SignalVector,
) -> None:
    """
    Ensure the transition from current to proposed signals follows the safe sequence:
    GREEN → YELLOW → ALL_RED → GREEN (for new phase)
    
    A GREEN phase must not transition directly to a conflicting GREEN phase.
    """
    current_greens = current_signals.green_directions()
    proposed_greens = proposed_signals.green_directions()

    if not current_greens or not proposed_greens:
        return  # No GREEN on either side, transition is trivially safe

    # Check: are the new greens in a different phase than the old greens?
    current_phase = _directions_to_phase(current_greens)
    proposed_phase = _directions_to_phase(proposed_greens)

    if current_phase and proposed_phase and current_phase != proposed_phase:
        # Direct GREEN-to-GREEN across conflicting phases is forbidden
        raise SafetyViolationError(
            f"Direct GREEN→GREEN transition from {current_phase.value} to "
            f"{proposed_phase.value} is forbidden. Must pass through YELLOW→ALL_RED first."
        )


def _directions_to_phase(directions: Set[Direction]) -> Phase:
    """Map a set of directions to their phase, or None if unrecognized."""
    for phase, dirs in PHASE_DIRECTIONS.items():
        if directions.issubset(dirs):
            return phase
    return None


def get_phase_for_direction(direction: Direction) -> Phase:
    """Return the phase that contains the given direction."""
    for phase, dirs in PHASE_DIRECTIONS.items():
        if direction in dirs:
            return phase
    raise ValueError(f"Direction {direction} not found in any configured phase")


def is_direction_in_phase(direction: Direction, phase: Phase) -> bool:
    """Check if a direction belongs to the given phase."""
    return direction in PHASE_DIRECTIONS[phase]


def get_opposing_phase(phase: Phase) -> Phase:
    """Get the conflicting/opposing phase."""
    conflicts = CONFLICTING_PHASES[phase]
    if len(conflicts) != 1:
        raise ValueError(f"Expected exactly one conflicting phase, got {len(conflicts)}")
    return next(iter(conflicts))


def are_phases_conflicting(phase_a: Phase, phase_b: Phase) -> bool:
    """Check if two phases are conflicting."""
    return phase_b in CONFLICTING_PHASES.get(phase_a, frozenset())


def validate_signal_vector_for_phase(
    signal_vector: SignalVector,
    expected_phase: Phase,
    expected_state: SignalState,
) -> bool:
    """
    Validate that the signal vector matches expected state for a phase.
    Returns True if all directions in the phase have the expected state
    and all other directions are RED.
    """
    phase_dirs = PHASE_DIRECTIONS[expected_phase]
    for direction in Direction:
        expected = expected_state if direction in phase_dirs else SignalState.RED
        actual = signal_vector.get(direction)
        if actual != expected:
            return False
    return True

