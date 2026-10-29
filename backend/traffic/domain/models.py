"""
Domain value objects and entities for the Factory Traffic Management System.
Pure Python — no framework dependencies.

These are plain Python data classes representing domain concepts.
They are NOT Django models.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, FrozenSet, List, Optional, Set

from .enums import (
    CommandStatus,
    DeviceHealth,
    Direction,
    OperatingMode,
    Phase,
    SignalState,
    TransitionState,
    VehicleType,
    PHASE_DIRECTIONS,
)


@dataclass(frozen=True)
class PhaseConfig:
    """Immutable configuration for a traffic phase."""
    phase: Phase
    directions: FrozenSet[Direction]

    @staticmethod
    def default_configs() -> List['PhaseConfig']:
        """Return the default phase configurations for a standard 4-way junction."""
        return [
            PhaseConfig(phase=Phase.NORTH_SOUTH, directions=frozenset({Direction.NORTH, Direction.SOUTH})),
            PhaseConfig(phase=Phase.EAST_WEST, directions=frozenset({Direction.EAST, Direction.WEST})),
        ]


@dataclass(frozen=True)
class SignalVector:
    """Immutable mapping of each direction to its signal state."""
    north: SignalState
    south: SignalState
    east: SignalState
    west: SignalState

    def as_dict(self) -> Dict[str, str]:
        return {
            Direction.NORTH.value: self.north.value,
            Direction.SOUTH.value: self.south.value,
            Direction.EAST.value: self.east.value,
            Direction.WEST.value: self.west.value,
        }

    @staticmethod
    def from_dict(d: Dict[str, str]) -> 'SignalVector':
        return SignalVector(
            north=SignalState(d.get("NORTH", "RED")),
            south=SignalState(d.get("SOUTH", "RED")),
            east=SignalState(d.get("EAST", "RED")),
            west=SignalState(d.get("WEST", "RED")),
        )

    @staticmethod
    def all_red() -> 'SignalVector':
        return SignalVector(
            north=SignalState.RED,
            south=SignalState.RED,
            east=SignalState.RED,
            west=SignalState.RED,
        )

    @staticmethod
    def all_unknown() -> 'SignalVector':
        return SignalVector(
            north=SignalState.UNKNOWN,
            south=SignalState.UNKNOWN,
            east=SignalState.UNKNOWN,
            west=SignalState.UNKNOWN,
        )

    @staticmethod
    def for_phase(phase: Phase) -> 'SignalVector':
        """Create a signal vector with GREEN for the given phase's directions, RED for others."""
        dirs = PHASE_DIRECTIONS[phase]
        return SignalVector(
            north=SignalState.GREEN if Direction.NORTH in dirs else SignalState.RED,
            south=SignalState.GREEN if Direction.SOUTH in dirs else SignalState.RED,
            east=SignalState.GREEN if Direction.EAST in dirs else SignalState.RED,
            west=SignalState.GREEN if Direction.WEST in dirs else SignalState.RED,
        )

    @staticmethod
    def yellow_for_phase(phase: Phase) -> 'SignalVector':
        """Create a signal vector with YELLOW for the given phase's directions, RED for others."""
        dirs = PHASE_DIRECTIONS[phase]
        return SignalVector(
            north=SignalState.YELLOW if Direction.NORTH in dirs else SignalState.RED,
            south=SignalState.YELLOW if Direction.SOUTH in dirs else SignalState.RED,
            east=SignalState.YELLOW if Direction.EAST in dirs else SignalState.RED,
            west=SignalState.YELLOW if Direction.WEST in dirs else SignalState.RED,
        )

    def get(self, direction: Direction) -> SignalState:
        return {
            Direction.NORTH: self.north,
            Direction.SOUTH: self.south,
            Direction.EAST: self.east,
            Direction.WEST: self.west,
        }[direction]

    def has_green(self) -> bool:
        return any(s == SignalState.GREEN for s in [self.north, self.south, self.east, self.west])

    def green_directions(self) -> Set[Direction]:
        result = set()
        for d, s in [(Direction.NORTH, self.north), (Direction.SOUTH, self.south),
                      (Direction.EAST, self.east), (Direction.WEST, self.west)]:
            if s == SignalState.GREEN:
                result.add(d)
        return result

    def has_conflicting_green(self) -> bool:
        """Check if GREEN directions belong to conflicting phases."""
        greens = self.green_directions()
        if len(greens) <= 1:
            return False
        # Check if all green directions belong to the same phase
        for phase, dirs in PHASE_DIRECTIONS.items():
            if greens.issubset(dirs):
                return False
        return True


@dataclass
class WaitingVehicle:
    """A vehicle waiting in a traffic queue."""
    vehicle_id: str
    vehicle_type: VehicleType
    direction: Direction
    arrived_at: datetime
    priority: int  # Derived from vehicle_type


@dataclass
class JunctionStateSnapshot:
    """
    A snapshot of the current state of a junction.
    Used for domain logic decisions — does NOT contain persistence metadata.
    """
    junction_id: str
    mode: OperatingMode
    current_phase: Phase
    transition_state: TransitionState
    desired_signals: SignalVector
    actual_signals: SignalVector
    controller_health: DeviceHealth
    active_emergency_direction: Optional[Direction]
    next_transition_at: Optional[datetime]
    version: int  # For optimistic concurrency control
    queues: Dict[Direction, int] = field(default_factory=dict)
    waiting_vehicles: Dict[Direction, List[WaitingVehicle]] = field(default_factory=dict)
    phase_started_at: Optional[datetime] = None
    manual_direction: Optional[Direction] = None

    def is_safe_for_operations(self) -> bool:
        """Check if the junction is in a state safe for normal operations."""
        return (
            self.controller_health in (DeviceHealth.ONLINE, DeviceHealth.WARNING)
            and self.mode != OperatingMode.DEGRADED
        )


@dataclass(frozen=True)
class TransitionResult:
    """Result of a state machine transition decision."""
    new_phase: Optional[Phase]
    new_transition_state: TransitionState
    new_desired_signals: SignalVector
    new_mode: Optional[OperatingMode]
    next_transition_at: Optional[datetime]
    reason: str
    phase_changed: bool = False


@dataclass(frozen=True)
class SchedulingDecision:
    """Result of the scheduling algorithm."""
    recommended_phase: Phase
    scores: Dict[Phase, float]
    reason: str
    should_switch: bool

