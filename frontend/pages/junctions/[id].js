import { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { fetchJunctionDetail, fetchJunctionStatus, fetchJunctionHistory } from '../../lib/api';
import IntersectionVisual from '../../components/IntersectionVisual';
import ManualControls from '../../components/ManualControls';
import SimulationPanel from '../../components/SimulationPanel';
import AuditHistory from '../../components/AuditHistory';
import AlertBanner from '../../components/AlertBanner';

export default function JunctionDetail() {
  const router = useRouter();
  const { id } = router.query;

  const [junction, setJunction] = useState(null);
  const [status, setStatus] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastPollTime, setLastPollTime] = useState(null);

  const pollTimerRef = useRef(null);
  const isMountedRef = useRef(true);

  const refreshData = async (background = false) => {
    if (!id) return;
    try {
      if (!background) setLoading(true);

      const [jData, sData, hData] = await Promise.all([
        fetchJunctionDetail(id),
        fetchJunctionStatus(id),
        fetchJunctionHistory(id, 30),
      ]);

      if (isMountedRef.current) {
        setJunction(jData);
        setStatus(sData);
        setHistory(hData.history || []);
        setError(null);
        setLastPollTime(new Date());
      }
    } catch (err) {
      if (isMountedRef.current) {
        setError(err.message || 'Error communicating with junction control server');
      }
    } finally {
      if (isMountedRef.current && !background) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    isMountedRef.current = true;
    if (id) {
      refreshData(false);

      // Poll authoritative state every 4 seconds
      pollTimerRef.current = setInterval(() => {
        refreshData(true);
      }, 4000);
    }

    return () => {
      isMountedRef.current = false;
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [id]);

  if (!id) return null;

  return (
    <div className="space-y-6">
      {/* Back Link & Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800 gap-3">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="p-2 rounded-lg bg-slate-900 border border-slate-800 hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
          >
            ←
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-white">
                {junction ? junction.name : `Junction ${id}`}
              </h1>
              <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-amber-400">
                Gate Node {id}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Authoritative controller status with non-blocking transition scheduling.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 text-xs font-mono">
          <span className="text-slate-500">
            {lastPollTime ? `Polled: ${lastPollTime.toLocaleTimeString()}` : 'Connecting...'}
          </span>
          <button
            onClick={() => refreshData(false)}
            disabled={loading}
            className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 disabled:opacity-50 transition-colors"
          >
            ↻ Sync Now
          </button>
        </div>
      </div>

      {/* Global Error Notice */}
      {error && (
        <div className="p-3 bg-rose-950/80 border border-rose-800 rounded-xl text-xs text-rose-200 flex justify-between items-center">
          <span>⚠️ {error}</span>
          <button onClick={() => refreshData(false)} className="underline text-xs hover:text-white">Retry</button>
        </div>
      )}

      {/* Alert Banner for emergencies, controller offline, or mismatches */}
      {status && (
        <AlertBanner
          activeEmergency={status.active_emergency}
          controllerStatus={status.controller_status}
          desiredSignals={status.desired_signals}
          actualSignals={status.actual_signals}
          transitionState={status.transition_state}
        />
      )}

      {loading && !status ? (
        <div className="p-16 text-center text-slate-500 bg-slate-900 border border-slate-800 rounded-xl">
          Querying junction telemetry...
        </div>
      ) : status ? (
        <>
          {/* Main 2-Column Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left Column: Visual Intersection & Queues (7 cols) */}
            <div className="lg:col-span-7 space-y-6">
              <IntersectionVisual
                desiredSignals={status.desired_signals || {}}
                actualSignals={status.actual_signals || {}}
                queues={status.queues || {}}
                activeEmergency={status.active_emergency}
                currentPhase={status.phase}
                transitionState={status.transition_state}
              />

              {/* Status Breakdown card */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
                <h3 className="font-semibold text-slate-200 text-sm uppercase tracking-wider mb-3">
                  📊 Authoritative Controller Telemetry
                </h3>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
                  <div className="bg-slate-950/60 p-2.5 rounded border border-slate-800">
                    <span className="text-[10px] text-slate-500 uppercase block">Operating Mode</span>
                    <strong className="text-amber-400 text-sm">{status.mode}</strong>
                  </div>
                  <div className="bg-slate-950/60 p-2.5 rounded border border-slate-800">
                    <span className="text-[10px] text-slate-500 uppercase block">Active Phase</span>
                    <strong className="text-emerald-400 text-sm">{status.phase}</strong>
                  </div>
                  <div className="bg-slate-950/60 p-2.5 rounded border border-slate-800">
                    <span className="text-[10px] text-slate-500 uppercase block">Clearance State</span>
                    <strong className="text-blue-400 text-sm">{status.transition_state}</strong>
                  </div>
                  <div className="bg-slate-950/60 p-2.5 rounded border border-slate-800">
                    <span className="text-[10px] text-slate-500 uppercase block">Controller Hardware</span>
                    <strong className={status.controller_status === 'ONLINE' ? 'text-emerald-400 text-sm' : 'text-rose-400 text-sm'}>
                      {status.controller_status}
                    </strong>
                  </div>
                </div>

                {/* Pending commands list if any */}
                {status.pending_commands && status.pending_commands.length > 0 && (
                  <div className="mt-4 pt-3 border-t border-slate-800">
                    <span className="text-xs text-amber-400 font-semibold block mb-2 font-mono">
                      ⏳ Pending Controller Hardware Dispatches ({status.pending_commands.length})
                    </span>
                    <div className="space-y-1.5 max-h-32 overflow-y-auto font-mono text-[11px]">
                      {status.pending_commands.map((cmd) => (
                        <div key={cmd.command_id} className="bg-slate-950 p-2 rounded border border-slate-800 flex justify-between items-center text-slate-300">
                          <div>
                            <span className="font-bold text-amber-300">{cmd.command_id}</span>
                            <span className="text-slate-500 ml-2">[{cmd.status}]</span>
                          </div>
                          <span className="text-slate-400 text-[10px]">
                            {JSON.stringify(cmd.requested_signals)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Right Column: Controls & Simulation (5 cols) */}
            <div className="lg:col-span-5 space-y-6">
              <ManualControls
                junctionId={id}
                mode={status.mode}
                isDegraded={status.controller_status === 'OFFLINE' || status.mode === 'DEGRADED'}
                onActionSuccess={() => refreshData(true)}
              />

              <SimulationPanel
                junctionId={id}
                onEventSent={() => refreshData(true)}
              />
            </div>
          </div>

          {/* Bottom Full-Width Section: System Audit Trail */}
          <AuditHistory history={history} loading={loading} />
        </>
      ) : null}
    </div>
  );
}

