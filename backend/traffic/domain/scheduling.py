"""
Traffic scheduling policy for the Factory Traffic Management System.
Pure Python — no framework dependencies.

Implements a weighted scoring algorithm considering:
- Queue size
- Vehicle priority
- Waiting time
- Starvation prevention

Scoring formula per phase:
    score = (queue_size × W_QUEUE) + (priority_sum × W_PRIORITY) + 
            (max_wait_seconds × W_WAIT) + (starvation_bonus × W_STARVATION)

Where starvation_bonus = 1.0 if max_wait > STARVATION_THRESHOLD else 0.0

Ties are resolved by preferring the opposing phase (to alternate traffic).
"""
from datetime import datetime
from typing import Dict, List, Optional

from .clock import Clock
from .enums import (
    Direction,
    OperatingMode,
    Phase,
    VehicleType,
    PHASE_DIRECTIONS,
    VEHICLE_PRIORITY,
    WEIGHT_QUEUE_SIZE,
    WEIGHT_PRIORITY,
    WEIGHT_WAIT_TIME,
    WEIGHT_STARVATION,
    STARVATION_THRESHOLD,
)
from .models import (
    JunctionStateSnapshot,
    SchedulingDecision,
    WaitingVehicle,
)
from .safety import get_opposing_phase


class TrafficScheduler:
    """
    Deterministic scheduling policy for traffic phase selection.
    
    Does NOT depend on Django, HTTP, or any framework.
    """

    def __init__(self, clock: Clock):
        self._clock = clock

    def evaluate(self, state: JunctionStateSnapshot) -> SchedulingDecision:
        """
        Evaluate which phase should be served next.
        
        Returns a SchedulingDecision with the recommended phase and scores.
        """
        now = self._clock.now()
        scores: Dict[Phase, float] = {}

        for phase in Phase:
            score = self._score_phase(phase, state, now)
            scores[phase] = score

        # Find the highest-scoring phase
        best_phase = max(scores, key=lambda p: scores[p])

        # Tie-breaking: prefer the opposing phase for alternation
        opposing = get_opposing_phase(state.current_phase)
        if scores[best_phase] == scores[opposing] and best_phase == state.current_phase:
            best_phase = opposing

        # Determine if we should switch
        should_switch = best_phase != state.current_phase

        return SchedulingDecision(
            recommended_phase=best_phase,
            scores=scores,
            reason=self._explain_decision(best_phase, scores, state),
            should_switch=should_switch,
        )

    def _score_phase(
        self,
        phase: Phase,
        state: JunctionStateSnapshot,
        now: datetime,
    ) -> float:
        """Calculate the scheduling score for a given phase."""
        directions = PHASE_DIRECTIONS[phase]
        total_queue = 0
        total_priority = 0
        max_wait_seconds = 0.0

        for direction in directions:
            # Queue size component
            queue_count = state.queues.get(direction, 0)
            total_queue += queue_count

            # Vehicle priority and waiting time components
            vehicles = state.waiting_vehicles.get(direction, [])
            for vehicle in vehicles:
                total_priority += VEHICLE_PRIORITY.get(vehicle.vehicle_type, 10)
                wait_seconds = (now - vehicle.arrived_at).total_seconds()
                if wait_seconds > max_wait_seconds:
                    max_wait_seconds = wait_seconds

        # Starvation bonus
        starvation_bonus = 1.0 if max_wait_seconds >= STARVATION_THRESHOLD else 0.0

        score = (
            total_queue * WEIGHT_QUEUE_SIZE
            + total_priority * WEIGHT_PRIORITY
            + max_wait_seconds * WEIGHT_WAIT_TIME
            + starvation_bonus * WEIGHT_STARVATION
        )

        return score

    def _explain_decision(
        self,
        best_phase: Phase,
        scores: Dict[Phase, float],
        state: JunctionStateSnapshot,
    ) -> str:
        """Generate a human-readable explanation of the scheduling decision."""
        parts = []
        for phase, score in sorted(scores.items(), key=lambda x: -x[1]):
            dirs = [d.value for d in PHASE_DIRECTIONS[phase]]
            parts.append(f"{phase.value} ({'/'.join(dirs)}): {score:.1f}")

        return (
            f"Recommended: {best_phase.value}. "
            f"Scores: {', '.join(parts)}. "
            f"Current phase: {state.current_phase.value}."
        )

