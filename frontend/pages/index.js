import { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { fetchJunctions, fetchJunctionStatus } from '../lib/api';
import SignalIndicator from '../components/SignalIndicator';

export default function Dashboard() {
  const [junctions, setJunctions] = useState([]);
  const [statuses, setStatuses] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const pollTimerRef = useRef(null);

  const loadData = async (isBackground = false) => {
    try {
      if (!isBackground) setLoading(true);
      const junctionList = await fetchJunctions();
      setJunctions(junctionList);

      const statusMap = {};
      for (const j of junctionList) {
        try {
          const s = await fetchJunctionStatus(j.junction_id);
          statusMap[j.junction_id] = s;
        } catch (err) {
          statusMap[j.junction_id] = { error: err.message };
        }
      }
      setStatuses(statusMap);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err.message || 'Unable to communicate with traffic control backend');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData(false);

    // Poll backend every 4 seconds with sensible cleanup
    pollTimerRef.current = setInterval(() => {
      loadData(true);
    }, 4000);

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, []);

  // Summary Metrics
  const totalVehicles = Object.values(statuses).reduce((acc, s) => {
    if (!s || !s.queues) return acc;
    return acc + Object.values(s.queues).reduce((sum, q) => sum + (q || 0), 0);
  }, 0);

  const activeEmergencies = Object.values(statuses).filter(
    (s) => s && s.active_emergency
  ).length;

  const onlineControllers = Object.values(statuses).filter(
    (s) => s && s.controller_status === 'ONLINE'
  ).length;

  return (
    <div className="space-y-6">
      {/* Top Banner & Stats */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
            <span>🏭 Factory Traffic Control Overview</span>
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-slate-300 font-normal">
              Live Polling (4s)
            </span>
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Real-time multi-junction status, queue metrics, and automated signal synchronization.
          </p>
        </div>

        <div className="flex items-center gap-3 text-xs font-mono">
          <span className="text-slate-400">
            Updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : 'Connecting...'}
          </span>
          <button
            onClick={() => loadData(false)}
            disabled={loading}
            className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 disabled:opacity-50 transition-colors"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="p-4 bg-rose-950/80 border border-rose-800 rounded-xl text-xs text-rose-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚠️</span>
            <span>{error} — ensure Django backend is running at http://127.0.0.1:8000</span>
          </div>
          <button onClick={() => loadData(false)} className="underline hover:text-white">Retry</button>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow">
          <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider block">Total Waiting Vehicles</span>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-bold text-amber-400 font-mono">{totalVehicles}</span>
            <span className="text-xs text-slate-500">Across all gates</span>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow">
          <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider block">Active Emergencies</span>
          <div className="mt-2 flex items-baseline justify-between">
            <span className={`text-2xl font-bold font-mono ${activeEmergencies > 0 ? 'text-rose-400 animate-pulse' : 'text-emerald-400'}`}>
              {activeEmergencies}
            </span>
            <span className="text-xs text-slate-500">Highest clearance priority</span>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow">
          <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider block">Hardware Controllers Online</span>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-bold text-emerald-400 font-mono">
              {onlineControllers} / {junctions.length}
            </span>
            <span className="text-xs text-slate-500">Signal units connected</span>
          </div>
        </div>
      </div>

      {/* Junction List */}
      <div className="space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
          Managed Factory Junctions ({junctions.length})
        </h2>

        {loading && junctions.length === 0 ? (
          <div className="p-12 text-center text-slate-500 bg-slate-900 border border-slate-800 rounded-xl">
            Loading junction telemetry...
          </div>
        ) : junctions.length === 0 ? (
          <div className="p-8 text-center text-slate-400 bg-slate-900 border border-slate-800 rounded-xl">
            No junctions found. Use the backend initialization to create Junction A.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {junctions.map((j) => {
              const status = statuses[j.junction_id] || {};
              const queues = status.queues || {};
              const desired = status.desired_signals || {};
              const actual = status.actual_signals || {};

              return (
                <div
                  key={j.junction_id}
                  className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg hover:border-slate-700 transition-all flex flex-col justify-between"
                >
                  <div>
                    {/* Header */}
                    <div className="flex items-start justify-between pb-3 border-b border-slate-800">
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="font-bold text-base text-white">{j.name}</h3>
                          <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-slate-800 text-amber-400 border border-slate-700">
                            ID: {j.junction_id}
                          </span>
                        </div>
                        <p className="text-xs text-slate-400 mt-0.5">
                          Mode: <strong className="text-slate-200">{status.mode || 'UNKNOWN'}</strong> | Phase: <strong className="text-slate-200">{status.phase || '—'}</strong>
                        </p>
                      </div>

                      <div className="flex flex-col items-end gap-1">
                        <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full ${
                          status.controller_status === 'ONLINE' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' :
                          status.controller_status === 'OFFLINE' ? 'bg-rose-950 text-rose-400 border border-rose-800' :
                          'bg-amber-950 text-amber-400 border border-amber-800'
                        }`}>
                          Controller: {status.controller_status || 'UNKNOWN'}
                        </span>
                        {status.active_emergency && (
                          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-rose-600 text-white animate-bounce">
                            EMERGENCY {status.active_emergency}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Queues & Signal state overview */}
                    <div className="py-4 grid grid-cols-4 gap-2 text-center">
                      {['NORTH', 'SOUTH', 'EAST', 'WEST'].map((dir) => (
                        <div key={dir} className="bg-slate-950/70 p-2.5 rounded-lg border border-slate-800/80 flex flex-col items-center">
                          <span className="text-[10px] font-mono font-bold text-slate-400 uppercase">{dir}</span>
                          <div className="my-1.5 flex gap-1">
                            <SignalIndicator state={desired[dir]} size="sm" />
                          </div>
                          <span className="text-xs font-mono font-bold text-amber-300">
                            Q: {queues[dir] || 0}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Card Footer */}
                  <div className="pt-3 border-t border-slate-800 flex items-center justify-between text-xs">
                    <span className="text-slate-400 font-mono text-[11px]">
                      State: <strong className="text-emerald-400">{status.transition_state || 'STABLE'}</strong>
                    </span>
                    <Link
                      href={`/junctions/${j.junction_id}`}
                      className="px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-300 border border-amber-500/30 hover:bg-amber-500/20 font-semibold transition-colors"
                    >
                      Open Control Panel →
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

