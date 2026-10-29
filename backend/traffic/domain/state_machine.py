"""
Traffic state machine for the Factory Traffic Management System.
Pure Python — no framework dependencies.

Implements the core state machine with the transition sequence:
    GREEN → YELLOW → ALL_RED → GREEN (next phase)

All transitions are validated against safety invariants.
The state machine is deterministic for identical inputs.
"""
from datetime import datetime, timedelta
from typing import Optional

from .clock import Clock
from .enums import (
    DeviceHealth,
    Direction,
    OperatingMode,
    Phase,
    SignalState,
    TransitionState,
    CONFLICTING_PHASES,
    PHASE_DIRECTIONS,
    DEFAULT_GREEN_DURATION,
    YELLOW_DURATION,
    ALL_RED_DURATION,
)
from .exceptions import (
    InvalidCommandError,
    InvalidTransitionError,
    SafetyViolationError,
    ControllerUncertainError,
)
from .models import (
    JunctionStateSnapshot,
    SignalVector,
    TransitionResult,
)
from .safety import (
    get_opposing_phase,
    get_phase_for_direction,
    validate_no_conflicting_green,
)


class TrafficStateMachine:
    """
    Deterministic traffic signal state machine.

    Controls the transition sequence: GREEN → YELLOW → ALL_RED → GREEN
    Enforces all safety invariants.
    Does NOT depend on Django, HTTP, or any framework.
    """

    def __init__(self, clock: Clock, green_duration: float = DEFAULT_GREEN_DURATION):
        self._clock = clock
        self._green_duration = green_duration

    # ── Phase transition processing ─────────────────────────────────────

    def process_due_transition(self, state: JunctionStateSnapshot) -> Optional[TransitionResult]:
        """
        Process a transition that is due based on persisted deadlines.
        Returns a TransitionResult if a transition should occur, None otherwise.

        This is the main entry point for the transition worker.
        Re-reads state from the snapshot (which should be freshly loaded from DB).
        """
        now = self._clock.now()

        # Cannot process transitions in DEGRADED mode
        if state.mode == OperatingMode.DEGRADED:
            return None

        # No transition scheduled
        if state.next_transition_at is None:
            return None

        # Not yet due
        if now < state.next_transition_at:
            return None

        # Process based on current transition state
        if state.transition_state == TransitionState.STABLE:
            return self._begin_yellow(state, now)
        elif state.transition_state == TransitionState.YELLOW:
            return self._begin_all_red(state, now)
        elif state.transition_state == TransitionState.ALL_RED:
            return self._begin_green(state, now)
        else:
            # TRANSITIONING — waiting for controller ACK, don't advance
            return None

    def _begin_yellow(self, state: JunctionStateSnapshot, now: datetime) -> TransitionResult:
        """Transition from STABLE (GREEN) to YELLOW for current phase."""
        new_signals = SignalVector.yellow_for_phase(state.current_phase)

        return TransitionResult(
            new_phase=state.current_phase,  # Phase doesn't change yet
            new_transition_state=TransitionState.YELLOW,
            new_desired_signals=new_signals,
            new_mode=None,  # Mode doesn't change
            next_transition_at=now + timedelta(seconds=YELLOW_DURATION),
            reason=f"GREEN→YELLOW for {state.current_phase.value}",
            phase_changed=False,
        )

    def _begin_all_red(self, state: JunctionStateSnapshot, now: datetime) -> TransitionResult:
        """Transition from YELLOW to ALL_RED."""
        return TransitionResult(
            new_phase=state.current_phase,  # Phase doesn't change yet
            new_transition_state=TransitionState.ALL_RED,
            new_desired_signals=SignalVector.all_red(),
            new_mode=None,
            next_transition_at=now + timedelta(seconds=ALL_RED_DURATION),
            reason=f"YELLOW→ALL_RED clearance for {state.current_phase.value}",
            phase_changed=False,
        )

    def _begin_green(self, state: JunctionStateSnapshot, now: datetime) -> TransitionResult:
        """
        Transition from ALL_RED to GREEN for the next phase.
        Determines next phase based on mode and scheduling.
        """
        next_phase = self._determine_next_phase(state)
        new_signals = SignalVector.for_phase(next_phase)

        # Validate safety before committing
        validate_no_conflicting_green(new_signals)

        # Determine mode after transition
        new_mode = self._determine_mode_after_green(state, next_phase)

        next_deadline = (
            None
            if new_mode in (OperatingMode.MANUAL, OperatingMode.EMERGENCY)
            else now + timedelta(seconds=self._green_duration)
        )

        return TransitionResult(
            new_phase=next_phase,
            new_transition_state=TransitionState.STABLE,
            new_desired_signals=new_signals,
            new_mode=new_mode,
            next_transition_at=next_deadline,
            reason=f"ALL_RED→GREEN for {next_phase.value}",
            phase_changed=(next_phase != state.current_phase),
        )

    def _determine_next_phase(self, state: JunctionStateSnapshot) -> Phase:
        """Determine which phase should go GREEN next based on operating mode."""
        if state.mode == OperatingMode.EMERGENCY and state.active_emergency_direction:
            # Emergency: go to the phase containing the emergency direction
            return get_phase_for_direction(state.active_emergency_direction)

        if state.mode == OperatingMode.MANUAL and state.manual_direction:
            # Manual: go to the phase containing the requested direction
            return get_phase_for_direction(state.manual_direction)

        # Automatic: alternate to the opposing phase by default
        # (Scheduling service will have set the target before initiating transition)
        return get_opposing_phase(state.current_phase)

    def _determine_mode_after_green(
        self, state: JunctionStateSnapshot, next_phase: Phase
    ) -> Optional[OperatingMode]:
        """Determine the operating mode after a GREEN transition completes."""
        if state.mode == OperatingMode.EMERGENCY:
            # Stay in EMERGENCY until explicitly cleared
            return OperatingMode.EMERGENCY
        if state.mode == OperatingMode.MANUAL:
            # Stay in MANUAL until explicitly released
            return OperatingMode.MANUAL
        return OperatingMode.AUTOMATIC

    # ── Emergency preemption ────────────────────────────────────────────

    def initiate_emergency_preemption(
        self,
        state: JunctionStateSnapshot,
        emergency_direction: Direction,
    ) -> Optional[TransitionResult]:
        """
        Initiate emergency preemption.
        If the emergency direction is already in the current GREEN phase, no transition needed.
        Otherwise, begin safe transition sequence.
        """
        emergency_phase = get_phase_for_direction(emergency_direction)

        # If already in the right phase and STABLE, no transition needed
        if state.current_phase == emergency_phase and state.transition_state == TransitionState.STABLE:
            return TransitionResult(
                new_phase=state.current_phase,
                new_transition_state=TransitionState.STABLE,
                new_desired_signals=state.desired_signals,
                new_mode=OperatingMode.EMERGENCY,
                next_transition_at=state.next_transition_at,
                reason=f"Emergency from {emergency_direction.value} — already in correct phase",
                phase_changed=False,
            )

        # If already transitioning toward the emergency phase, don't restart
        if state.transition_state != TransitionState.STABLE:
            # Already in transition, just update mode
            return TransitionResult(
                new_phase=state.current_phase,
                new_transition_state=state.transition_state,
                new_desired_signals=state.desired_signals,
                new_mode=OperatingMode.EMERGENCY,
                next_transition_at=state.next_transition_at,
                reason=f"Emergency from {emergency_direction.value} — transition already in progress",
                phase_changed=False,
            )

        # Need to start transition: begin YELLOW immediately
        now = self._clock.now()
        new_signals = SignalVector.yellow_for_phase(state.current_phase)

        return TransitionResult(
            new_phase=state.current_phase,
            new_transition_state=TransitionState.YELLOW,
            new_desired_signals=new_signals,
            new_mode=OperatingMode.EMERGENCY,
            next_transition_at=now + timedelta(seconds=YELLOW_DURATION),
            reason=f"Emergency preemption from {emergency_direction.value} — starting YELLOW",
            phase_changed=False,
        )

    # ── Manual control ──────────────────────────────────────────────────

    def initiate_manual_green(
        self,
        state: JunctionStateSnapshot,
        direction: Direction,
    ) -> TransitionResult:
        """
        Initiate manual GREEN request for a specific direction.
        Uses the same safe transition mechanism as automatic scheduling.
        """
        # Validate direction
        target_phase = get_phase_for_direction(direction)

        # Cannot initiate during degraded mode
        if state.mode == OperatingMode.DEGRADED:
            raise InvalidCommandError(
                "Cannot process manual command in DEGRADED mode. "
                "Controller health must be restored first."
            )

        # Emergency overrides manual
        if state.mode == OperatingMode.EMERGENCY:
            raise InvalidCommandError(
                "Cannot process manual command during active EMERGENCY. "
                "Emergency must be cleared first."
            )

        # If already in the target phase and STABLE, just switch to manual mode
        if state.current_phase == target_phase and state.transition_state == TransitionState.STABLE:
            return TransitionResult(
                new_phase=state.current_phase,
                new_transition_state=TransitionState.STABLE,
                new_desired_signals=state.desired_signals,
                new_mode=OperatingMode.MANUAL,
                next_transition_at=None,  # Manual mode: no automatic transition
                reason=f"Manual GREEN for {direction.value} — already in correct phase",
                phase_changed=False,
            )

        # If already transitioning, reject — wait for current transition to complete
        if state.transition_state != TransitionState.STABLE:
            raise InvalidCommandError(
                f"Cannot initiate manual GREEN while transition is in progress "
                f"(current state: {state.transition_state.value}). "
                f"Wait for current transition to complete."
            )

        # Start safe transition: begin YELLOW
        now = self._clock.now()
        new_signals = SignalVector.yellow_for_phase(state.current_phase)

        return TransitionResult(
            new_phase=state.current_phase,
            new_transition_state=TransitionState.YELLOW,
            new_desired_signals=new_signals,
            new_mode=OperatingMode.MANUAL,
            next_transition_at=now + timedelta(seconds=YELLOW_DURATION),
            reason=f"Manual GREEN request for {direction.value} — starting YELLOW",
            phase_changed=False,
        )

    def return_to_automatic(self, state: JunctionStateSnapshot) -> TransitionResult:
        """Return the junction to automatic mode."""
        now = self._clock.now()

        # If stable, just switch mode and schedule next transition
        if state.transition_state == TransitionState.STABLE:
            return TransitionResult(
                new_phase=state.current_phase,
                new_transition_state=TransitionState.STABLE,
                new_desired_signals=state.desired_signals,
                new_mode=OperatingMode.AUTOMATIC,
                next_transition_at=now + timedelta(seconds=self._green_duration),
                reason="Returned to AUTOMATIC mode",
                phase_changed=False,
            )

        # If transitioning, keep transition going but switch mode
        return TransitionResult(
            new_phase=state.current_phase,
            new_transition_state=state.transition_state,
            new_desired_signals=state.desired_signals,
            new_mode=OperatingMode.AUTOMATIC,
            next_transition_at=state.next_transition_at,
            reason="Returned to AUTOMATIC mode (transition in progress)",
            phase_changed=False,
        )

    # ── Recovery ────────────────────────────────────────────────────────

    def compute_recovery_state(self, state: JunctionStateSnapshot) -> TransitionResult:
        """
        Compute safe recovery state after restart.
        
        Conservative policy:
        - If controller state is unknown, enter DEGRADED mode with ALL_RED
        - If state was in transition, enter ALL_RED and re-evaluate
        - Never blindly advance to GREEN after restart
        """
        now = self._clock.now()

        # If controller is offline/unknown, go to DEGRADED with ALL_RED
        if state.controller_health in (DeviceHealth.OFFLINE, DeviceHealth.UNKNOWN):
            return TransitionResult(
                new_phase=state.current_phase,
                new_transition_state=TransitionState.ALL_RED,
                new_desired_signals=SignalVector.all_red(),
                new_mode=OperatingMode.DEGRADED,
                next_transition_at=None,  # No automatic transition in DEGRADED
                reason="Recovery: controller state uncertain, entering DEGRADED with ALL_RED",
                phase_changed=False,
            )

        # If was in mid-transition, go to ALL_RED and re-evaluate
        if state.transition_state in (TransitionState.YELLOW, TransitionState.TRANSITIONING):
            return TransitionResult(
                new_phase=state.current_phase,
                new_transition_state=TransitionState.ALL_RED,
                new_desired_signals=SignalVector.all_red(),
                new_mode=state.mode if state.mode != OperatingMode.DEGRADED else OperatingMode.AUTOMATIC,
                next_transition_at=now + timedelta(seconds=ALL_RED_DURATION),
                reason="Recovery: was in mid-transition, entering ALL_RED for safe clearance",
                phase_changed=False,
            )

        # If was in ALL_RED, continue to next phase
        if state.transition_state == TransitionState.ALL_RED:
            return TransitionResult(
                new_phase=state.current_phase,
                new_transition_state=TransitionState.ALL_RED,
                new_desired_signals=SignalVector.all_red(),
                new_mode=state.mode if state.mode != OperatingMode.DEGRADED else OperatingMode.AUTOMATIC,
                next_transition_at=now + timedelta(seconds=ALL_RED_DURATION),
                reason="Recovery: was in ALL_RED, scheduling next transition",
                phase_changed=False,
            )

        # If was STABLE (GREEN), check if actual matches desired
        if state.actual_signals != state.desired_signals:
            # Mismatch — enter ALL_RED conservatively
            return TransitionResult(
                new_phase=state.current_phase,
                new_transition_state=TransitionState.ALL_RED,
                new_desired_signals=SignalVector.all_red(),
                new_mode=OperatingMode.DEGRADED,
                next_transition_at=None,
                reason="Recovery: desired/actual mismatch, entering DEGRADED with ALL_RED",
                phase_changed=False,
            )

        # Stable and confirmed — resume normal operation
        return TransitionResult(
            new_phase=state.current_phase,
            new_transition_state=TransitionState.STABLE,
            new_desired_signals=state.desired_signals,
            new_mode=OperatingMode.AUTOMATIC,
            next_transition_at=now + timedelta(seconds=self._green_duration),
            reason="Recovery: state confirmed, resuming AUTOMATIC",
            phase_changed=False,
        )

