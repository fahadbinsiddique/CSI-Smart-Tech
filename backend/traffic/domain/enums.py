"""
Domain enums for the Factory Traffic Management System.
Pure Python — no framework dependencies.
"""
from enum import Enum, unique


@unique
class Direction(str, Enum):
    """Traffic directions at a junction."""
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


@unique
class SignalState(str, Enum):
    """Physical signal states."""
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    UNKNOWN = "UNKNOWN"  # When physical state is uncertain


@unique
class Phase(str, Enum):
    """Traffic phases — groups of directions that move together."""
    NORTH_SOUTH = "NORTH_SOUTH"
    EAST_WEST = "EAST_WEST"


@unique
class TransitionState(str, Enum):
    """States within a phase transition sequence."""
    STABLE = "STABLE"          # Phase is holding (GREEN active)
    YELLOW = "YELLOW"          # Active phase is YELLOW, preparing to switch
    ALL_RED = "ALL_RED"        # All directions RED for safe clearance
    TRANSITIONING = "TRANSITIONING"  # Waiting for controller confirmation


@unique
class OperatingMode(str, Enum):
    """Junction operating modes."""
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"
    DEGRADED = "DEGRADED"  # Controller failure or unknown state


@unique
class VehicleType(str, Enum):
    """Supported vehicle types with priority ordering."""
    EMERGENCY = "EMERGENCY"
    TRUCK = "TRUCK"
    FORKLIFT = "FORKLIFT"
    EMPLOYEE_VEHICLE = "EMPLOYEE_VEHICLE"


@unique
class EventType(str, Enum):
    """Sensor event types."""
    VEHICLE_ARRIVED = "VEHICLE_ARRIVED"
    VEHICLE_CLEARED = "VEHICLE_CLEARED"


@unique
class CommandType(str, Enum):
    """Control command types."""
    MANUAL_GREEN_REQUEST = "MANUAL_GREEN_REQUEST"
    RETURN_TO_AUTOMATIC = "RETURN_TO_AUTOMATIC"


@unique
class CommandStatus(str, Enum):
    """Status of a controller command."""
    PENDING = "PENDING"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    SUPERSEDED = "SUPERSEDED"


@unique
class DeviceHealth(str, Enum):
    """Health status of physical devices."""
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    WARNING = "WARNING"
    UNKNOWN = "UNKNOWN"


@unique
class ProcessingStatus(str, Enum):
    """Status of event processing."""
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


@unique
class AuditEventType(str, Enum):
    """Types of audit log entries."""
    VEHICLE_ARRIVED = "VEHICLE_ARRIVED"
    VEHICLE_CLEARED = "VEHICLE_CLEARED"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    REJECTED_EVENT = "REJECTED_EVENT"
    QUEUE_UPDATED = "QUEUE_UPDATED"
    SCHEDULING_DECISION = "SCHEDULING_DECISION"
    SIGNAL_TRANSITION_REQUESTED = "SIGNAL_TRANSITION_REQUESTED"
    DESIRED_STATE_CHANGED = "DESIRED_STATE_CHANGED"
    CONTROLLER_COMMAND_SENT = "CONTROLLER_COMMAND_SENT"
    CONTROLLER_ACK_RECEIVED = "CONTROLLER_ACK_RECEIVED"
    CONTROLLER_ACK_REJECTED = "CONTROLLER_ACK_REJECTED"
    CONTROLLER_TIMEOUT = "CONTROLLER_TIMEOUT"
    CONTROLLER_FAILURE = "CONTROLLER_FAILURE"
    EMERGENCY_DETECTED = "EMERGENCY_DETECTED"
    EMERGENCY_CLEARED = "EMERGENCY_CLEARED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    RETURN_TO_AUTOMATIC = "RETURN_TO_AUTOMATIC"
    DEVICE_STATUS_CHANGED = "DEVICE_STATUS_CHANGED"
    MODE_CHANGED = "MODE_CHANGED"
    RECOVERY_EVENT = "RECOVERY_EVENT"
    PHASE_CHANGED = "PHASE_CHANGED"
    TRANSITION_STATE_CHANGED = "TRANSITION_STATE_CHANGED"
    SIGNAL_CHANGED = "SIGNAL_CHANGED"


# ── Priority mapping ────────────────────────────────────────────────────────
VEHICLE_PRIORITY = {
    VehicleType.EMERGENCY: 100,
    VehicleType.TRUCK: 30,
    VehicleType.FORKLIFT: 20,
    VehicleType.EMPLOYEE_VEHICLE: 10,
}

# ── Phase configuration ─────────────────────────────────────────────────────
# Maps each phase to the set of directions that receive GREEN in that phase.
PHASE_DIRECTIONS = {
    Phase.NORTH_SOUTH: frozenset({Direction.NORTH, Direction.SOUTH}),
    Phase.EAST_WEST: frozenset({Direction.EAST, Direction.WEST}),
}

# Conflicting phases — phases that must NOT be GREEN simultaneously.
CONFLICTING_PHASES = {
    Phase.NORTH_SOUTH: frozenset({Phase.EAST_WEST}),
    Phase.EAST_WEST: frozenset({Phase.NORTH_SOUTH}),
}

# ── Timing defaults (seconds) ───────────────────────────────────────────────
DEFAULT_GREEN_DURATION = 30.0
YELLOW_DURATION = 5.0
ALL_RED_DURATION = 3.0  # Conservative default for factory safety
CONTROLLER_ACK_TIMEOUT = 10.0
EMERGENCY_TIMEOUT = 300.0  # 5 minutes stale emergency timeout
STARVATION_THRESHOLD = 90.0  # Seconds before starvation boost kicks in

# ── Scheduling weights ──────────────────────────────────────────────────────
WEIGHT_QUEUE_SIZE = 1.0
WEIGHT_PRIORITY = 3.0
WEIGHT_WAIT_TIME = 0.5
WEIGHT_STARVATION = 10.0  # Bonus when past starvation threshold

