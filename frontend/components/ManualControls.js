import { useState } from 'react';
import { postJunctionCommand } from '../lib/api';

export default function ManualControls({ junctionId, mode = 'AUTOMATIC', isDegraded = false, onActionSuccess }) {
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);

  const handleManualGreen = async (direction) => {
    setLoading(true);
    setError(null);
    setMsg(null);
    try {
      const res = await postJunctionCommand(junctionId, {
        command: 'MANUAL_GREEN_REQUEST',
        direction: direction,
      });
      setMsg(`Manual request sent for ${direction}: ${res.message || 'Accepted'}`);
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      setError(err.message || 'Failed to request manual green');
    } finally {
      setLoading(false);
    }
  };

  const handleReturnAuto = async () => {
    setLoading(true);
    setError(null);
    setMsg(null);
    try {
      const res = await postJunctionCommand(junctionId, {
        command: 'RETURN_TO_AUTOMATIC',
      });
      setMsg(`System restored to automatic mode: ${res.message || 'Accepted'}`);
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      setError(err.message || 'Failed to return to automatic mode');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
      <div className="flex items-center justify-between mb-4 pb-2 border-b border-slate-800">
        <div>
          <h3 className="font-semibold text-slate-200 text-sm tracking-wide uppercase flex items-center gap-2">
            <span>⚙️ Manual Control Override</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Operator commands are validated and safely scheduled through yellow-clearance sequence.
          </p>
        </div>
        <span className={`text-xs px-2.5 py-1 rounded-full font-bold font-mono ${
          mode === 'MANUAL' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
          mode === 'EMERGENCY' ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' :
          mode === 'DEGRADED' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30' :
          'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
        }`}>
          {mode}
        </span>
      </div>

      {msg && (
        <div className="mb-3 px-3 py-2 bg-emerald-950/60 border border-emerald-800 text-emerald-300 rounded text-xs flex justify-between items-center">
          <span>{msg}</span>
          <button onClick={() => setMsg(null)} className="text-emerald-500 hover:text-white">✕</button>
        </div>
      )}

      {error && (
        <div className="mb-3 px-3 py-2 bg-rose-950/60 border border-rose-800 text-rose-300 rounded text-xs flex justify-between items-center">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-rose-500 hover:text-white">✕</button>
        </div>
      )}

      {isDegraded && (
        <div className="mb-3 px-3 py-2 bg-orange-950/60 border border-orange-800 text-orange-300 rounded text-xs">
          ⚠️ Controller health is degraded or offline. Manual commands may be rejected by safety validation.
        </div>
      )}

      <div className="space-y-3">
        <div>
          <label className="text-xs font-semibold text-slate-400 block mb-2">Request Directional Green Phase:</label>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {['NORTH', 'SOUTH', 'EAST', 'WEST'].map((dir) => (
              <button
                key={dir}
                onClick={() => handleManualGreen(dir)}
                disabled={loading || isDegraded}
                className="px-3 py-2 text-xs font-semibold rounded-lg bg-slate-800 hover:bg-slate-700 active:bg-amber-600/30 text-slate-200 border border-slate-700 disabled:opacity-40 transition-colors"
              >
                Green {dir}
              </button>
            ))}
          </div>
        </div>

        <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between">
          <span className="text-xs text-slate-400">Release override to normal loop:</span>
          <button
            onClick={handleReturnAuto}
            disabled={loading || mode === 'AUTOMATIC'}
            className="px-4 py-1.5 text-xs font-bold rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border border-emerald-500/40 disabled:opacity-30 transition-colors"
          >
            Return to Automatic
          </button>
        </div>
      </div>
    </div>
  );
}

