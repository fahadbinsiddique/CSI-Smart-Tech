# Factory Traffic Management System (FTMS)
### Industrial IoT & Autonomous Junction Control System

A production-grade, test-driven Factory Traffic Management System designed for internal roads within an automated garment manufacturing facility. Built with a framework-agnostic Python domain core, Django REST Framework backend with SQLite persistence, and an industrial Next.js React operator dashboard.

---

## Table of Contents
1. [Project Overview and Scope](#1-project-overview-and-scope)
2. [Technology Stack](#2-technology-stack)
3. [Architecture and Directory Structure](#3-architecture-and-directory-structure)
4. [Key Domain Entities and Database Design](#4-key-domain-entities-and-database-design)
5. [State-Machine Rules and Safety Invariants](#5-state-machine-rules-and-safety-invariants)
6. [Traffic Scheduling Algorithm](#6-traffic-scheduling-algorithm)
7. [Emergency Preemption Policy](#7-emergency-preemption-policy)
8. [Manual Control Policy](#8-manual-control-policy)
9. [Desired vs. Actual State & Controller ACK Workflow](#9-desired-vs-actual-state--controller-ack-workflow)
10. [Concurrency Strategy and SQLite Limitations](#10-concurrency-strategy-and-sqlite-limitations)
11. [Event Idempotency and Ordering Policy](#11-event-idempotency-and-ordering-policy)
12. [Failure Handling and Restart Recovery](#12-failure-handling-and-restart-recovery)
13. [API Endpoint Reference with Example Payloads](#13-api-endpoint-reference-with-example-payloads)
14. [Backend Setup and Run Instructions](#14-backend-setup-and-run-instructions)
15. [Frontend Setup and Run Instructions](#15-frontend-setup-and-run-instructions)
16. [Database Migration Commands](#16-database-migration-commands)
17. [Domain, API, and Integration Test Commands](#17-domain-api-and-integration-test-commands)
18. [Instructions for Running the Transition Worker](#18-instructions-for-running-the-transition-worker)
19. [Step-by-Step Demonstration of Assessment Scenarios](#19-step-by-step-demonstration-of-assessment-scenarios)
20. [Known Limitations and Incomplete Features](#20-known-limitations-and-incomplete-features)
21. [Future Improvements](#21-future-improvements)
22. [AI / Tool Usage](#22-ai--tool-usage)
23. [Assumptions / Questions / Requirement Issues](#assumptions--questions--requirement-issues)

---

## 1. Project Overview and Scope

In garment manufacturing plants, high-traffic internal roads are shared by forklifts transferring textile bundles, delivery freight trucks, maintenance equipment, employee shuttles, and emergency first-responder vehicles. Uncontrolled intersections risk collisions, logistical bottlenecks, and emergency vehicle delays.

The **Factory Traffic Management System (FTMS)** provides:
- **Centralized Safety Enforcement:** Guarantees that conflicting traffic phases (e.g., North/South vs. East/West) never simultaneously receive GREEN.
- **Strict Clearance Transitions:** Direct GREEN-to-GREEN transitions between conflicting directions are strictly blocked; all phase changes mandate `GREEN → YELLOW (5s) → ALL_RED (3s) → GREEN`.
- **Idempotent Telemetry Processing:** High-frequency optical/loop sensors submit arrival and clearance events deduplicated by immutable `event_id` keys.
- **Priority-Weighted Scheduling:** Prevents forklift/truck delays while dynamically elevating emergency response vehicles and mitigating starvation of lower-priority employee traffic.
- **Separation of Desired vs. Actual Controller State:** Distinguishes between what the control system commands and what the physical IoT controller has confirmed via uniquely correlated `command_id` ACKs (`uuid4`-based, simulated ACKs are flagged with `is_simulated=True`).
- **Fail-Safe Operation & Restart Recovery:** Transitions to conservative clearance (`ALL_RED`) or `DEGRADED` modes when hardware communication is lost or servers restart.
- **Operator Dashboard & Telemetry Simulator:** A responsive Next.js web application offering real-time status polling, visual junction animation, manual overrides, and an evaluator simulation console.

---

## 2. Technology Stack

### Backend
- **Python 3.12+**
- **Django 5.2+** & **Django REST Framework (DRF)**
- **SQLite 3** (configured with atomic transactions and explicit concurrency checks)
- **Django CORS Headers**
- **Pytest & Pytest-Django**

### Frontend
- **Next.js 14** (Pages Router)
- **React 18**
- **Tailwind CSS 3**
- **Lucide Icons**
- Client-side interval polling (~4 seconds) with cancellation on component unmount and zero-flash re-rendering.

---

## 3. Architecture and Directory Structure

The system enforces strict hexagonal / clean-architecture boundaries. The **core traffic domain** is completely isolated in `traffic/domain/` and has zero imports from Django, DRF, HTTP, database ORM, or frontend code.

```
Factory Traffic Management System/
├── backend/
│   ├── config/                     # Django project settings, WSGI, URLs
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── traffic/
│   │   ├── domain/                 # Pure Python Domain Logic (Zero Framework Imports)
│   │   │   ├── enums.py            # Direction, SignalState, Phase, OperatingMode, etc.
│   │   │   ├── models.py           # SignalVector, Snapshots, WaitingVehicle value objects
│   │   │   ├── safety.py           # Invariant validation rules
│   │   │   ├── state_machine.py    # Transition engine & clearance sequencing
│   │   │   ├── scheduling.py       # Weighted priority scoring & starvation prevention
│   │   │   ├── exceptions.py       # Explicit domain exceptions
│   │   │   └── clock.py            # Clock abstraction (SystemClock & FakeClock)
│   │   ├── application/            # Application Use-Case Services
│   │   │   ├── event_service.py    # Sensor event ingestion & deduplication
│   │   │   ├── command_service.py  # Operator manual override & emergency preemption
│   │   │   ├── transition_service.py # Non-blocking phase deadline processing
│   │   │   ├── controller_service.py # Physical/simulated ACK & telemetry handling
│   │   │   └── recovery_service.py # Crash & restart recovery orchestrator
│   │   ├── infrastructure/         # Persistence & External Adapters
│   │   │   ├── models.py           # Django ORM models (Junction, State, Vehicles, Commands, Audit)
│   │   │   ├── repositories.py     # Data access layer & transactional encapsulation
│   │   │   └── simulated_controller.py # Simulated physical hardware ACK emitter
│   │   ├── api/                    # REST Interface
│   │   │   ├── serializers.py      # DRF request/response validators
│   │   │   ├── views.py            # HTTP controller endpoints
│   │   │   ├── urls.py             # Route declarations
│   │   │   └── exception_handler.py # Domain-to-HTTP error status code mapper
│   │   ├── management/commands/    # CLI & Background Workers
│   │   │   └── run_transition_worker.py # Recoverable background state transition worker
│   │   └── tests/                  # Automated Test Suite (95 tests)
│   │       ├── test_domain.py      # Pure domain state machine unit tests
│   │       ├── test_scheduling.py  # Priority, starvation, and weight tests
│   │       ├── test_api.py         # HTTP endpoints & DRF serializer tests
│   │       └── test_scenarios.py   # Complete end-to-end evaluation scenarios
│   ├── manage.py
│   ├── requirements.txt
│   └── pytest.ini
│
├── frontend/
│   ├── components/
│   │   ├── Layout.js               # Industrial application layout & navigation
│   │   ├── IntersectionVisual.js   # 4-way visual road intersection with signal lamps
│   │   ├── SignalIndicator.js      # Individual traffic lamp (RED/YELLOW/GREEN/UNKNOWN)
│   │   ├── ManualControls.js       # Operator green request & automatic mode toggle
│   │   ├── SimulationPanel.js      # Telemetry generator for evaluator testing
│   │   ├── AlertBanner.js          # Prominent safety, mismatch & emergency alerts
│   │   └── AuditHistory.js         # Append-only activity log viewer
│   ├── lib/
│   │   └── api.js                  # Frontend API client
│   ├── pages/
│   │   ├── _app.js
│   │   ├── index.js                # Factory overview & multi-junction dashboard
│   │   └── junctions/
│   │       └── [id].js             # Detailed single junction cockpit
│   ├── styles/globals.css
│   ├── package.json
│   ├── next.config.js
│   └── tailwind.config.js
│
├── prompt.md
└── README.md
```

---

## 4. Key Domain Entities and Database Design

### Core Domain Entities (Value Objects)
- `SignalVector`: Immutable representation of signals across all directions (`north`, `south`, `east`, `west`). Provides helper factories `for_phase()`, `yellow_for_phase()`, `all_red()`, and `all_unknown()`.
- `JunctionStateSnapshot`: Pure data snapshot containing current phase, mode, transition state, desired signals, confirmed actual signals, controller health, and queue representations.
- `WaitingVehicle`: Domain representation of a waiting queue entry containing `vehicle_id`, `vehicle_type`, `direction`, `arrived_at`, and integer `priority`.

### Database Schema (Django ORM Models)
1. **`Junction`**: Master entity defining `junction_id` (PK, string), `name`, and extensible `phase_config` JSON array.
2. **`JunctionState`**: One-to-one mapping with `Junction`. Tracks:
   - `mode`: `AUTOMATIC`, `MANUAL`, `EMERGENCY`, `DEGRADED`.
   - `current_phase`: Active phase (`NORTH_SOUTH`, `EAST_WEST`).
   - `transition_state`: Current clearance point (`STABLE`, `YELLOW`, `ALL_RED`, `TRANSITIONING`).
   - `desired_signals`: JSON dictionary of backend's intended signal states.
   - `actual_signals`: JSON dictionary of controller-confirmed physical states.
   - `controller_health`: `ONLINE`, `OFFLINE`, `DEGRADED`, `WARNING`, `UNKNOWN`.
   - `active_emergency_direction`: Direction of currently preemption vehicle (or null).
   - `next_transition_at`: Target timestamp for the next automated clearance advance.
   - `version`: Monotonically increasing counter for optimistic concurrency checking.
3. **`WaitingVehicle`**: Queue table with unique constraint on `(junction, vehicle_id)`. Tracks arrival timestamp, priority score, and triggering event ID.
4. **`ProcessedEvent`**: Deduplication registry with `event_id` as unique primary index. Tracks ingestion status (`ACCEPTED`, `DUPLICATE`, `REJECTED`), raw sensor timestamp, and processing timestamp.
5. **`ControllerCommand`**: Dispatch tracking with unique `command_id`. Tracks status (`PENDING`, `SENT`, `ACKNOWLEDGED`, `FAILED`, `TIMED_OUT`, `SUPERSEDED`), timeout thresholds, and physical ACK payloads.
6. **`AuditEntry`**: Append-only log recording every vehicle arrival, vehicle clearance, scheduling decision, signal change, manual override, emergency preemption, and controller status change.

---

## 5. State-Machine Rules and Safety Invariants

### Transition Sequence
Phase changes must strictly proceed through the safe clearance pipeline:
$$\text{STABLE GREEN} \xrightarrow{\text{due / preemption}} \text{YELLOW (5s)} \xrightarrow{} \text{ALL\_RED (3s)} \xrightarrow{} \text{NEXT STABLE GREEN (30s)}$$

### Mandatory Safety Invariants (Domain-Enforced)
1. **Zero Conflicting Green:** Conflicting phases (`NORTH_SOUTH` vs `EAST_WEST`) can never have simultaneous GREEN signals under any circumstance.
2. **No Direct GREEN-to-GREEN Switch:** Any phase change across conflicting paths must clear vehicular traffic through YELLOW and ALL_RED. Direct GREEN-to-GREEN transition requests raise `SafetyViolationError`.
3. **Conservative Clearance ALL_RED:** During ALL_RED, all directions are actively commanded to RED for a configurable 3.0 seconds to permit vehicles in the intersection box to clear before granting new right-of-way.
4. **Overrides Cannot Bypass State Machine:** Neither operator manual commands nor emergency preemptions can force arbitrary signal states directly; they set system intent and trigger the state machine's safe clearance progression.
5. **Deterministic Logic:** Given identical queue state, mode, and clock time, domain decisions are 100% deterministic.

---

## 6. Traffic Scheduling Algorithm

In `AUTOMATIC` mode, when a GREEN phase expires (default 30 seconds), the `TrafficScheduler` evaluates waiting traffic to determine whether to hold or switch phases.

### Scoring Formula
For each phase $P \in \{\text{NORTH\_SOUTH}, \text{EAST\_WEST}\}$:

$$\text{Score}(P) = (Q_P \times W_Q) + (\text{PrioritySum}_P \times W_P) + (\text{MaxWaitSeconds}_P \times W_W) + (\text{StarvationBonus}_P \times W_S)$$

Where:
- $Q_P$: Total queue count across directions in phase $P$.
- $W_Q = 1.0$: Weight for queue size.
- $\text{PrioritySum}_P$: Sum of priority values of all vehicles waiting in phase $P$:
  - `EMERGENCY`: $100$
  - `TRUCK`: $30$
  - `FORKLIFT`: $20$
  - `EMPLOYEE_VEHICLE`: $10$
- $W_P = 3.0$: Weight for vehicle priority.
- $\text{MaxWaitSeconds}_P$: Waiting duration of the oldest waiting vehicle in phase $P$.
- $W_W = 0.5$: Weight for waiting time.
- $\text{StarvationBonus}_P$: Applied if $\text{MaxWaitSeconds}_P \ge 90.0$ seconds ($W_S = 10.0$) to guarantee lower-priority employee traffic is never trapped indefinitely by continuous forklift/truck arrival.

### Tie-Breaking
When scores are equal, the scheduler alternates to the opposing phase to maintain steady traffic flow.

---

## 7. Emergency Preemption Policy

When a sensor or operator submits an `EMERGENCY` vehicle arrival:
1. **Arrival from Current Phase:** If the emergency vehicle approaches in a direction already enjoying GREEN, the mode updates to `EMERGENCY` and the current phase is maintained.
2. **Arrival from Conflicting Phase:** The system immediately terminates the active green phase by starting the YELLOW clearance transition (5 seconds), followed by ALL_RED (3 seconds), and then grants GREEN to the emergency direction's phase.
3. **Multiple Competing Emergencies:** If emergency vehicles arrive from both North/South and East/West simultaneously, the state machine serves the earliest-arrived emergency direction first, clears it, and subsequently transitions to the opposing emergency direction.
4. **Emergency Supersedes Manual:** An emergency request immediately overrides operator manual control.
5. **Emergency Clearance:** An emergency mode remains active until the vehicle leaves via `VEHICLE_CLEARED` or until an operator releases control.

---

## 8. Manual Control Policy

Factory administrators can take command of a junction via the REST API or Dashboard:
- `POST /api/junctions/<id>/commands/` with `{"command": "MANUAL_GREEN_REQUEST", "direction": "WEST"}`.
- If WEST is in the opposing phase, the state machine triggers `YELLOW → ALL_RED → GREEN (EAST_WEST)`.
- **Persistence:** Manual mode persists indefinitely until explicitly cancelled or an emergency occurs.
- **Release:** Sending `{"command": "RETURN_TO_AUTOMATIC"}` safely returns control to the automated scheduler.
- **Fail-Safe Rejection:** Manual commands issued during `DEGRADED` controller status or during active `EMERGENCY` are rejected with HTTP 400/409 errors.

---

## 9. Desired vs. Actual State & Controller ACK Workflow

In real-world automation, requesting a light to turn green does not guarantee the incandescent or LED lamp has actually changed state (relays fail, power trips, cables disconnect).

1. **Desired State:** Generated by the domain state machine and stored in `JunctionState.desired_signals`.
2. **Command Dispatch:** A `ControllerCommand` record is created with a unique `command_id` (e.g. `cmd-8a9f2bc4`) and set to `PENDING`.
3. **Controller Confirmation:**
   - The physical controller (or simulated adapter) receives the command and responds via `POST /api/controller-events/` with `status: "ACK"` and `actual_signals`.
   - On valid ACK, `JunctionState.actual_signals` is updated and the command marked `ACKNOWLEDGED`.
4. **Timeout Handling:** If no ACK arrives within 10.0 seconds, the command is marked `TIMED_OUT` and controller health degrades to `WARNING` or `DEGRADED`.
5. **Stale/Duplicate ACK Rejection:** ACKs matching unknown, expired, or superseded `command_id` entries are safely logged and rejected without updating the confirmed signal state.

---

## 10. Concurrency Strategy and SQLite Limitations

### Concurrency Guarantees
- **Atomic Database Mutations:** All state changes and queue modifications are executed inside Django `transaction.atomic()` blocks.
- **Idempotency Locks:** Unique database index on `ProcessedEvent.event_id` ensures that concurrent submissions of identical sensor events are serialized and rejected at the storage engine level.
- **Optimistic Versioning:** `JunctionState` features an integer `version` field. Updates verify that the persisted version matches the read version, guarding against lost updates in concurrent worker threads.

### SQLite Considerations & Limitations
- **Locking Model:** SQLite uses database-level locking rather than row-level locking. While `select_for_update()` is supported syntactically, it locks the entire SQLite database file during write transactions.
- **Multi-Process Limitation:** For high-throughput production deployment across multiple container replicas, SQLite should be swapped for **PostgreSQL** with real row locks (`FOR UPDATE`) and connection pooling (PgBouncer).
- **Concurrency hardening:** SQLite is configured with atomic transactions, optimistic version checks on `JunctionState`, and a 20-second operational busy timeout. WAL mode is **not** enabled in the development configuration (documented limitation; PostgreSQL with `SELECT FOR UPDATE` is recommended for multi-replica production deployments).

---

## 11. Event Idempotency and Ordering Policy

- **Deduplication:** Every incoming sensor event requires an `event_id`. Duplicate IDs return HTTP 200 with status `DUPLICATE` and never increment queue counters twice.
- **Timestamp Distinctions:**
  1. `sensor_timestamp`: Time vehicle was detected in the field.
  2. `received_at`: Server arrival time.
  3. `processed_at`: Database commit timestamp.
- **Out-of-Order Clearances:** If a `VEHICLE_CLEARED` event arrives for a vehicle not found in the queue (e.g. sensor packet arrived out of sequence), the event is accepted with a diagnostic warning and queue counts are prevented from ever dropping below zero ($Q \ge 0$).

---

## 12. Failure Handling and Restart Recovery

### Hardware Failure Modes
- If a controller emits an `OFFLINE` status event, the junction enters `DEGRADED` mode.
- Signal states are marked `UNKNOWN` and automatic phase switching is halted immediately.
- Resuming requires the controller to report `ONLINE` followed by an explicit operational check.

### Server Restart Recovery
When the backend application restarts:
1. `RecoveryService.recover_all_junctions()` runs during worker initialization.
2. If a junction was mid-transition (`YELLOW` or `TRANSITIONING`), it is immediately set to `ALL_RED` for conservative clearance before resuming.
3. If controller communication was unconfirmed or desired/actual signals mismatch, the junction enters `DEGRADED` with `ALL_RED`.
4. The system **never** blindly advances to GREEN after an ungraceful restart.

---

## 13. API Endpoint Reference with Example Payloads

### Junction Endpoints
- `GET /api/junctions/` — List all registered junctions.
- `POST /api/junctions/` — Create junction.
  ```json
  {
    "junction_id": "B",
    "name": "Warehouse Junction B"
  }
  ```
- `GET /api/junctions/<id>/status/` — Retrieve authoritative status, queues, desired/actual signals, active emergencies, and pending commands.

### Sensor Telemetry
- `POST /api/sensor-events/` — Ingest vehicle arrival/clearance events.
  ```json
  {
    "event_id": "evt-10001",
    "junction_id": "A",
    "direction": "NORTH",
    "event_type": "VEHICLE_ARRIVED",
    "vehicle_id": "VH-501",
    "vehicle_type": "FORKLIFT",
    "sequence_no": 1501,
    "timestamp": "2026-10-05T10:15:20Z"
  }
  ```

### Control Commands
- `POST /api/junctions/<id>/commands/` — Manual override commands.
  ```json
  {
    "command": "MANUAL_GREEN_REQUEST",
    "direction": "WEST"
  }
  ```
  ```json
  {
    "command": "RETURN_TO_AUTOMATIC"
  }
  ```

### Controller Hardware Events
- `POST /api/controller-events/` — Hardware ACK or device status changes.
  ```json
  {
    "command_id": "cmd-8001",
    "junction_id": "A",
    "status": "ACK",
    "actual_signals": {
      "NORTH": "GREEN",
      "SOUTH": "GREEN",
      "EAST": "RED",
      "WEST": "RED"
    }
  }
  ```
  ```json
  {
    "junction_id": "A",
    "device_type": "SIGNAL_CONTROLLER",
    "status": "OFFLINE"
  }
  ```

### History Log
- `GET /api/junctions/<id>/history/?limit=50` — Query append-only audit trail.

---

## 14. Backend Setup and Run Instructions

### Prerequisites
- Python 3.12+

```bash
# Navigate to backend directory
cd backend

# Activate virtual environment
# Windows:
.\venv\Scripts\Activate.ps1
# Linux/macOS:
# source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Seed initial Junction A (if needed)
python -c "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup(); from traffic.infrastructure.repositories import JunctionRepository; repo = JunctionRepository(); repo.create('A', 'Factory Junction A') if not repo.exists('A') else None"

# Start the Django development server
python manage.py runserver 127.0.0.1:8000
```

Backend will be accessible at: `http://127.0.0.1:8000/api/`

---

## 15. Frontend Setup and Run Instructions

### Prerequisites
- Node.js 18+ and npm

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies (if not already installed)
npm install

# Build production bundle
npm run build

# Start Next.js server
npm run dev
```

Dashboard will be accessible at: `http://localhost:3000`

---

## 16. Database Migration Commands

```bash
cd backend
python manage.py makemigrations traffic
python manage.py migrate
```

---

## 17. Domain, API, and Integration Test Commands

The repository contains 95 comprehensive automated tests across domain rules, scheduling policies, REST endpoints, concurrency races, and end-to-end evaluation scenarios. All 95 tests pass as verified during the independent audit:

```bash
cd backend

# Run entire test suite
.\venv\Scripts\python.exe -m pytest -v

# Run only pure domain state machine & safety tests
.\venv\Scripts\python.exe -m pytest traffic/tests/test_domain.py -v

# Run scheduling policy tests (starvation, weighting)
.\venv\Scripts\python.exe -m pytest traffic/tests/test_scheduling.py -v

# Run API and controller tests
.\venv\Scripts\python.exe -m pytest traffic/tests/test_api.py -v

# Run end-to-end scenario tests (Scenarios 1 through 9)
.\venv\Scripts\python.exe -m pytest traffic/tests/test_scenarios.py -v
```

---

## 18. Instructions for Running the Transition Worker

The transition worker is a non-blocking background process that monitors scheduled phase deadlines, executes due transitions, verifies command timeouts, and simulates hardware ACKs:

```bash
cd backend
python manage.py run_transition_worker --interval 2
```

### Options:
- `--interval <seconds>`: Polling loop frequency (default: 2.0s).
- `--no-recovery`: Skip startup recovery sweep.
- `--no-simulate`: Disable automatic simulated ACKs (used when testing physical MQTT hardware).

---

## 19. Step-by-Step Demonstration of Assessment Scenarios

All 9 assessment scenarios can be demonstrated either via automated pytest or directly through the web dashboard at `http://localhost:3000/junctions/A`:

1. **Scenario 1 (Normal Traffic):** Submit 3 vehicle arrivals from NORTH and 1 from EAST using the simulator panel. Observe queues increase to 3 and 1.
2. **Scenario 2 (Priority Traffic):** Submit an employee vehicle on NORTH and a TRUCK on EAST. Observe priority ordering reflected in the audit log and scheduling decisions.
3. **Scenario 3 (Emergency Preemption):** While NORTH_SOUTH has GREEN, click **"🚨 Emergency (East)"**. Notice the system immediately initiates a safe clearance transition: NORTH_SOUTH turns YELLOW for 5s, enters ALL_RED for 3s, and then safely switches to EAST_WEST GREEN.
4. **Scenario 4 (Manual Override):** Click **"Green WEST"** in the manual control card. The state machine clears traffic and locks WEST into green. Click **"Return to Automatic"** to restore automated scheduling.
5. **Scenario 5 (Duplicate Event):** Click **"🔁 Duplicate Event Test"**. The first click accepts the event; subsequent clicks return `DUPLICATE` status and do not double-increment queues.
6. **Scenario 6 (Vehicle Clearance):** Submit arrival for `VH-501` on NORTH, then click **"- Send VEHICLE_CLEARED"**. Observe queue decreases by 1.
7. **Scenario 7 (Controller Failure):** Click **"🔌 Sim Controller Offline"**. The system enters `DEGRADED` mode, actual signals turn to `UNKNOWN`, and transitions halt.
8. **Scenario 8 (Restart Recovery):** Stop the backend during a transition. Restart it or run `python manage.py run_transition_worker`. Observe that unconfirmed states safely transition into `ALL_RED`.
9. **Scenario 9 (Concurrent Events):** Run `pytest traffic/tests/test_scenarios.py -k test_scenario_9_concurrent_events`. Conflicting simultaneous arrival, emergency, and override requests are transactionally ordered without safety invariant violations.

---

## 20. Known Limitations and Incomplete Features

1. **SQLite Database Locking:** Under heavy multi-process write concurrency, SQLite may raise temporary busy errors. For multi-replica production environments, PostgreSQL with connection pooling is recommended.
2. **Single Phase Set Active:** The current implementation configures standard dual-phase four-way junctions (`NORTH_SOUTH` and `EAST_WEST`). Dedicated turn lanes (e.g., protected left turns) are not yet modeled in the default junction phase configuration.
3. **HTTP Polling vs. WebSockets:** The frontend dashboard polls the API every 4 seconds. While robust and resilient to disconnections, WebSockets/Server-Sent Events (SSE) would provide sub-second telemetry updates.

---

## 21. Future Improvements

1. **MQTT Protocol Broker:** Implement an MQTT sidecar adapter subscribing to `factory/junction/+/telemetry` and publishing to `factory/junction/+/commands`.
2. **PostgreSQL Migration:** Transition database configuration to PostgreSQL with row-level locks (`SELECT FOR UPDATE`).
3. **Dynamic Phase Editor:** Provide a UI configuration interface to define arbitrary junction topologies, 3-way T-junctions, and multi-phase roundabouts.
4. **Machine Learning Traffic Optimization:** Implement reinforcement learning models to adjust green phase durations based on historical textile manufacturing shifts.

---

## 22. AI / Tool Usage

During the development of this project, AI coding assistance (Antigravity with Claude Opus 4.6 and Gemini 3.8 Flash) was utilized for:
- Initial project scaffolding and directory structure layout.
- Generating boilerplate DRF serializers, URL configurations, and Next.js Tailwind component styling.
- Drafting unit test cases for the domain state machine and API endpoints.

All architectural decisions, safety invariant designs, deterministic transition logic, concurrency safeguards, and edge-case validations were engineered and verified against the assessment specification.

---

## Assumptions / Questions / Requirement Issues

### 1. Conflicting Movements and Phase Definitions
- **Issue:** The specification simplified junctions to NORTH, SOUTH, EAST, and WEST, with phases `NORTH_SOUTH` and `EAST_WEST`, but did not specify turn conflict rules (e.g. unprotected left turns).
- **Decision:** Assumed that all traffic moving within a phase (`NORTH` and `SOUTH`) is non-conflicting (through traffic and right turns), while any movement crossing the opposing phase (`EAST` and `WEST`) is strictly conflicting. The domain architecture utilizes extensible `PHASE_DIRECTIONS` sets so custom movement rules can be injected without changing the transition engine.

### 2. ALL_RED Duration and Scope
- **Issue:** The specification suggested an internal `ALL_RED` state but left its duration and definition unspecified.
- **Decision:** Configured `ALL_RED_DURATION = 3.0` seconds as a conservative industrial default. `ALL_RED` is defined as all four directions (`NORTH`, `SOUTH`, `EAST`, `WEST`) simultaneously showing physical `RED` signals to allow vehicles within the junction box to clear safely before opposing traffic receives green.

### 3. Event Ordering and Authoritative Timestamp
- **Issue:** Edge sensors transmit a `timestamp` and a `sequence_no`, but network latency can cause packets to arrive out of order.
- **Decision:** For deduplication and processing state, `event_id` is treated as the primary unique key. The server records both `sensor_timestamp` (telemetry capture) and `received_at` (server arrival). If a vehicle clearance event arrives without an existing arrival record (due to out-of-order delivery), the system accepts the clearance, logs a diagnostic anomaly in the audit trail, and clamps queues at zero ($Q \ge 0$).

### 4. Duplicate Sensor Events
- **Issue:** Sensor retries or network replays can deliver identical arrival events.
- **Decision:** Idempotency is enforced at the database level via a unique constraint on `ProcessedEvent.event_id` and unique `(junction, vehicle_id)` on `WaitingVehicle`. Repeated event IDs return an HTTP 200 response with status `DUPLICATE` and do not alter the queue count or trigger redundant phase transitions.

### 5. Scheduling Weights and Starvation Mitigation
- **Issue:** The specification specified priority order `EMERGENCY > TRUCK > FORKLIFT > EMPLOYEE_VEHICLE` but left weights and starvation protection unspecified.
- **Decision:** Implemented explicit linear weights: Queue count $\times 1.0$, Priority sum $\times 3.0$, Wait seconds $\times 0.5$. To prevent starvation where continuous heavy forklift/truck traffic traps employee vehicles, any vehicle waiting over 90 seconds receives a $+10.0$ starvation bonus, guaranteeing eventual phase transition.

### 6. Emergency Preemption and Clearance
- **Issue:** The specification did not define how competing emergencies are resolved or when an emergency is considered cleared.
- **Decision:** An emergency request immediately triggers the safe yellow/all-red transition sequence. If multiple emergencies arrive, the earliest-arrived emergency direction is served first. Emergency mode persists until a corresponding `VEHICLE_CLEARED` event for the emergency vehicle is ingested or the operator manually resets the mode via `RETURN_TO_AUTOMATIC`. The 300-second `EMERGENCY_TIMEOUT` constant is defined as reserved policy but is not enforced by the running system; stale emergencies require explicit clearance or operator release.

### 7. Manual Control Expiration and Conflict Resolution
- **Issue:** The specification did not define manual override duration or how competing operator commands are handled.
- **Decision:** Manual control persists until an explicit `RETURN_TO_AUTOMATIC` command is submitted, providing predictable industrial safety. If two operators issue concurrent manual commands, the optimistic version check ensures only the first valid request succeeds while the second receives an explanatory error. Active emergency preemption always overrides manual control.

### 8. Physical Controller ACK Timeout and Mismatch Policy
- **Issue:** Behavior during missing or delayed physical controller acknowledgements was unspecified.
- **Decision:** Commands awaiting ACK have a 10.0-second timeout. If no ACK is received, the command transitions to `TIMED_OUT` and controller status is downgraded to `WARNING` or `DEGRADED`. The system never fabricates confirmed actual states; until an ACK is confirmed, the frontend and API explicitly report a desired/actual state mismatch.

### 9. Restart Recovery During Signal Transitions
- **Issue:** Behavior if the backend restarts during `YELLOW` or `ALL_RED` was unspecified.
- **Decision:** The application runs `RecoveryService.recover_all_junctions()` upon startup. If a junction was in the middle of a clearance transition or if controller state cannot be confirmed, it is safely transitioned to `ALL_RED` clearance and re-evaluated. The system never blindly assumes a pre-restart green state is active.

### 10. SQLite Concurrency Model
- **Issue:** The assessment requires SQLite for development, which lacks PostgreSQL-style row-level locks.
- **Decision:** SQLite transactions are wrapped in atomic blocks with an explicit version counter on `JunctionState` to detect concurrent write conflicts. The limitations of SQLite are clearly documented, and repository boundaries are kept clean to enable a seamless future transition to PostgreSQL.

