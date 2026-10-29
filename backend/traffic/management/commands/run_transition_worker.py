"""
Django management command to run the transition worker.

Periodically processes due transitions, checks command timeouts,
and handles recovery on startup.

Usage:
    python manage.py run_transition_worker [--interval 2]

How it works:
    - On startup, runs recovery for all junctions
    - Polls every `interval` seconds (default: 2)
    - Processes due transitions via TransitionService
    - Checks for timed-out controller commands
    - Simulates controller ACKs for the simulated controller

How to resume after restart:
    Simply restart the worker. The recovery service will evaluate
    all junction states and apply conservative recovery (ALL_RED)
    for any uncertain states.

How missed deadlines are handled:
    The worker re-reads persisted state on each cycle. If a deadline
    was missed (e.g., server was down), the transition will be processed
    immediately on the next cycle. The state machine re-evaluates
    based on current state, not stale in-memory state.
"""
import logging
import time
import signal
import sys

from django.core.management.base import BaseCommand
from django.db import connection

from traffic.application.recovery_service import RecoveryService
from traffic.application.transition_service import TransitionService
from traffic.infrastructure.simulated_controller import SimulatedControllerService

logger = logging.getLogger('traffic.worker')


class Command(BaseCommand):
    help = 'Run the transition worker for processing traffic signal transitions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=float,
            default=2.0,
            help='Polling interval in seconds (default: 2)',
        )
        parser.add_argument(
            '--no-recovery',
            action='store_true',
            help='Skip recovery on startup',
        )
        parser.add_argument(
            '--no-simulate',
            action='store_true',
            help='Disable simulated controller ACKs',
        )

    def handle(self, *args, **options):
        interval = options['interval']
        skip_recovery = options['no_recovery']
        no_simulate = options['no_simulate']

        self.stdout.write(self.style.SUCCESS(
            f'Starting transition worker (interval={interval}s)'
        ))

        # Setup graceful shutdown
        self._running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Run recovery on startup
        if not skip_recovery:
            try:
                recovery = RecoveryService()
                recovered = recovery.recover_all_junctions()
                if recovered:
                    self.stdout.write(self.style.WARNING(
                        f'Recovery applied to {recovered} junction(s)'
                    ))
                else:
                    self.stdout.write(self.style.SUCCESS(
                        'All junctions in safe state, no recovery needed'
                    ))
            except Exception as e:
                logger.error(f"Recovery failed: {e}", exc_info=True)
                self.stdout.write(self.style.ERROR(f'Recovery error: {e}'))

        # Main worker loop
        transition_service = TransitionService()
        sim_controller = None if no_simulate else SimulatedControllerService()

        while self._running:
            try:
                # Process due transitions
                processed = transition_service.process_all_due_transitions()
                if processed:
                    logger.info(f"Processed {processed} transition(s)")

                # Check command timeouts
                timed_out = transition_service.check_command_timeouts()
                if timed_out:
                    logger.info(f"Timed out {timed_out} command(s)")

                # Clear stale emergencies (300s documented timeout)
                cleared_emergencies = transition_service.clear_stale_emergencies()
                if cleared_emergencies:
                    logger.info(
                        f"Cleared {cleared_emergencies} stale emergency(ies)"
                    )

                # Simulate controller ACKs
                if sim_controller:
                    acked = sim_controller.process_pending_commands()
                    if acked:
                        logger.info(f"Simulated {acked} ACK(s)")

                # Close stale DB connections
                connection.close_if_unusable_or_obsolete()

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Worker cycle error: {e}", exc_info=True)

            time.sleep(interval)

        self.stdout.write(self.style.SUCCESS('Transition worker stopped'))

    def _signal_handler(self, signum, frame):
        self.stdout.write(self.style.WARNING('\nShutdown signal received...'))
        self._running = False

