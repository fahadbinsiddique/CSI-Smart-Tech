import { useState } from 'react';
import { postSensorEvent, postControllerEvent } from '../lib/api';

export default function SimulationPanel({ junctionId, onEventSent }) {
  const [vehicleId, setVehicleId] = useState('VH-101');
  const [vehicleType, setVehicleType] = useState('FORKLIFT');
  const [direction, setDirection] = useState('NORTH');
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState(null);

  // Submit vehicle arrival
  const handleArrival = async (customType, customDir) => {
    setLoading(true);
    setFeedback(null);
    const chosenType = customType || vehicleType;
    const chosenDir = customDir || direction;
    const evtId = `evt-${Date.now().toString().slice(-6)}`;
    const vId = customType === 'EMERGENCY' ? `EMG-${Math.floor(100 + Math.random() * 900)}` : vehicleId;

    try {
      const res = await postSensorEvent({
        event_id: evtId,
        junction_id: junctionId,
        direction: chosenDir,
        event_type: 'VEHICLE_ARRIVED',
        vehicle_id: vId,
        vehicle_type: chosenType,
        sequence_no: Math.floor(1000 + Math.random() * 9000),
        timestamp: new Date().toISOString(),
      });
      setFeedback({ type: 'success', msg: `Arrival Accepted: ${vId} (${chosenType}) at ${chosenDir}` });
      if (onEventSent) onEventSent();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Arrival failed' });
    } finally {
      setLoading(false);
    }
  };

  // Submit vehicle clearance
  const handleClearance = async () => {
    setLoading(true);
    setFeedback(null);
    const evtId = `evt-clr-${Date.now().toString().slice(-6)}`;
    try {
      const res = await postSensorEvent({
        event_id: evtId,
        junction_id: junctionId,
        direction: direction,
        event_type: 'VEHICLE_CLEARED',
        vehicle_id: vehicleId,
        sequence_no: Math.floor(1000 + Math.random() * 9000),
        timestamp: new Date().toISOString(),
      });
      setFeedback({ type: 'success', msg: `Clearance Accepted: ${vehicleId} cleared from ${direction}` });
      if (onEventSent) onEventSent();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Clearance failed' });
    } finally {
      setLoading(false);
    }
  };

  // Submit Duplicate Event
  const handleDuplicateTest = async () => {
    setLoading(true);
    setFeedback(null);
    const fixedEvtId = 'evt-dup-test-001';
    try {
      const res = await postSensorEvent({
        event_id: fixedEvtId,
        junction_id: junctionId,
        direction: direction,
        event_type: 'VEHICLE_ARRIVED',
        vehicle_id: `VH-DUP-${Math.floor(10 + Math.random() * 90)}`,
        vehicle_type: 'TRUCK',
        timestamp: new Date().toISOString(),
      });
      setFeedback({
        type: res.status === 'DUPLICATE' ? 'warning' : 'success',
        msg: `Idempotency Test Result: [Status: ${res.status}] ${res.message || 'Processed'}`
      });
      if (onEventSent) onEventSent();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message });
    } finally {
      setLoading(false);
    }
  };

  // Controller Health Toggle
  const handleControllerHealth = async (newHealth) => {
    setLoading(true);
    setFeedback(null);
    try {
      const res = await postControllerEvent({
        junction_id: junctionId,
        device_type: 'SIGNAL_CONTROLLER',
        status: newHealth,
        event_id: `status-${Date.now().toString().slice(-5)}`,
      });
      setFeedback({ type: 'success', msg: `Controller hardware set to: ${newHealth}` });
      if (onEventSent) onEventSent();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg space-y-4">
      <div className="flex items-center justify-between pb-2 border-b border-slate-800">
        <div>
          <h3 className="font-semibold text-slate-200 text-sm tracking-wide uppercase flex items-center gap-2">
            <span>🧪 Evaluator Simulator Console</span>
          </h3>
          <p className="text-xs text-slate-400">
            Simulate field sensor telemetry, emergency priority preemption, and physical controller hardware.
          </p>
        </div>
      </div>

      {feedback && (
        <div className={`px-3 py-2 rounded text-xs flex justify-between items-center ${
          feedback.type === 'error' ? 'bg-rose-950/80 border border-rose-800 text-rose-300' :
          feedback.type === 'warning' ? 'bg-amber-950/80 border border-amber-800 text-amber-300' :
          'bg-emerald-950/80 border border-emerald-800 text-emerald-300'
        }`}>
          <span>{feedback.msg}</span>
          <button onClick={() => setFeedback(null)} className="text-slate-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Quick Scenario Triggers */}
      <div className="bg-slate-950/60 p-3 rounded-lg border border-slate-800/80">
        <span className="text-[11px] font-bold uppercase tracking-wider text-amber-400 block mb-2">
          ⚡ One-Click Scenarios
        </span>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <button
            onClick={() => handleArrival('EMERGENCY', 'EAST')}
            disabled={loading}
            className="px-2.5 py-1.5 text-xs font-bold rounded bg-rose-600/30 hover:bg-rose-600/50 text-rose-300 border border-rose-500/40 disabled:opacity-50 flex items-center justify-center gap-1.5"
          >
            <span>🚨 Emergency (East)</span>
          </button>
          <button
            onClick={() => handleArrival('TRUCK', 'NORTH')}
            disabled={loading}
            className="px-2.5 py-1.5 text-xs font-bold rounded bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/40 disabled:opacity-50"
          >
            🚛 Priority Truck (North)
          </button>
          <button
            onClick={handleDuplicateTest}
            disabled={loading}
            className="px-2.5 py-1.5 text-xs font-bold rounded bg-purple-600/20 hover:bg-purple-600/30 text-purple-300 border border-purple-500/40 disabled:opacity-50"
          >
            🔁 Duplicate Event Test
          </button>
          <button
            onClick={() => handleControllerHealth('OFFLINE')}
            disabled={loading}
            className="px-2.5 py-1.5 text-xs font-bold rounded bg-red-950/80 hover:bg-red-900 text-red-300 border border-red-700/60 disabled:opacity-50"
          >
            🔌 Sim Controller Offline
          </button>
        </div>
      </div>

      {/* Manual telemetry input */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className="text-[11px] text-slate-400 block mb-1">Direction</label>
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200"
          >
            <option value="NORTH">NORTH</option>
            <option value="SOUTH">SOUTH</option>
            <option value="EAST">EAST</option>
            <option value="WEST">WEST</option>
          </select>
        </div>

        <div>
          <label className="text-[11px] text-slate-400 block mb-1">Vehicle Type</label>
          <select
            value={vehicleType}
            onChange={(e) => setVehicleType(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200"
          >
            <option value="FORKLIFT">FORKLIFT (P20)</option>
            <option value="TRUCK">TRUCK (P30)</option>
            <option value="EMPLOYEE_VEHICLE">EMPLOYEE_VEHICLE (P10)</option>
            <option value="EMERGENCY">EMERGENCY (P100)</option>
          </select>
        </div>

        <div>
          <label className="text-[11px] text-slate-400 block mb-1">Vehicle ID</label>
          <input
            type="text"
            value={vehicleId}
            onChange={(e) => setVehicleId(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200 font-mono"
            placeholder="VH-XXX"
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-2 pt-2 border-t border-slate-800">
        <button
          onClick={() => handleArrival()}
          disabled={loading}
          className="px-3 py-1.5 text-xs font-semibold rounded bg-emerald-600/30 hover:bg-emerald-600/40 text-emerald-300 border border-emerald-500/40 disabled:opacity-50"
        >
          + Send VEHICLE_ARRIVED
        </button>
        <button
          onClick={handleClearance}
          disabled={loading}
          className="px-3 py-1.5 text-xs font-semibold rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 disabled:opacity-50"
        >
          - Send VEHICLE_CLEARED
        </button>
        <div className="ml-auto flex items-center gap-1.5">
          <span className="text-[11px] text-slate-500">Controller Status:</span>
          <button
            onClick={() => handleControllerHealth('ONLINE')}
            disabled={loading}
            className="px-2 py-1 text-[11px] rounded bg-emerald-950 text-emerald-400 border border-emerald-800 hover:bg-emerald-900"
          >
            Set Online
          </button>
          <button
            onClick={() => handleControllerHealth('OFFLINE')}
            disabled={loading}
            className="px-2 py-1 text-[11px] rounded bg-rose-950 text-rose-400 border border-rose-800 hover:bg-rose-900"
          >
            Set Offline
          </button>
        </div>
      </div>
    </div>
  );
}

