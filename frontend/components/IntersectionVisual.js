import SignalIndicator from './SignalIndicator';

export default function IntersectionVisual({
  desiredSignals = {},
  actualSignals = {},
  queues = {},
  activeEmergency = null,
  currentPhase = 'NORTH_SOUTH',
  transitionState = 'STABLE'
}) {
  const directions = ['NORTH', 'SOUTH', 'EAST', 'WEST'];

  const getMismatch = (dir) => {
    const des = desiredSignals[dir] || 'UNKNOWN';
    const act = actualSignals[dir] || 'UNKNOWN';
    return des !== act;
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl relative overflow-hidden">
      <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
        <div>
          <h3 className="font-semibold text-slate-200 text-sm tracking-wide uppercase flex items-center gap-2">
            <span>🗺️ Physical Intersection Layout</span>
            <span className="text-xs font-mono font-normal text-slate-400">
              [Phase: <strong className="text-amber-400">{currentPhase}</strong> | State: <strong className="text-emerald-400">{transitionState}</strong>]
            </span>
          </h3>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-slate-700 border border-slate-500"></span>
            <span className="text-slate-400">Desired vs Actual Display</span>
          </div>
        </div>
      </div>

      {/* Visual Intersection Grid */}
      <div className="relative w-full max-w-md mx-auto aspect-square bg-slate-950/70 border border-slate-800/80 rounded-2xl p-4 flex items-center justify-center">
        {/* Asphalt road cross */}
        <div className="absolute inset-x-0 top-1/3 bottom-1/3 bg-slate-800/40 border-y border-dashed border-slate-700/60" />
        <div className="absolute inset-y-0 left-1/3 right-1/3 bg-slate-800/40 border-x border-dashed border-slate-700/60" />
        
        {/* Center Intersection Box */}
        <div className="absolute inset-1/3 bg-slate-800/80 border border-amber-500/30 rounded-lg flex flex-col items-center justify-center z-10 shadow-lg">
          <span className="text-[11px] font-bold tracking-widest text-amber-400/90 font-mono">JUNCTION</span>
          <span className="text-[10px] text-slate-300 font-mono font-medium">{currentPhase}</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded mt-1 font-semibold ${
            transitionState === 'STABLE' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' :
            transitionState === 'YELLOW' ? 'bg-amber-950 text-amber-400 border border-amber-800 animate-pulse' :
            transitionState === 'ALL_RED' ? 'bg-rose-950 text-rose-400 border border-rose-800 animate-pulse' :
            'bg-blue-950 text-blue-400'
          }`}>
            {transitionState}
          </span>
        </div>

        {/* NORTH Approach */}
        <div className="absolute top-2 left-1/2 -translate-x-1/2 flex flex-col items-center z-20">
          <div className="flex items-center gap-2 mb-1">
            <span className={`px-2 py-0.5 rounded text-xs font-bold font-mono ${
              activeEmergency === 'NORTH' ? 'bg-rose-600 text-white animate-bounce' : 'bg-slate-800 text-slate-200 border border-slate-700'
            }`}>
              NORTH {activeEmergency === 'NORTH' && '🚨'}
            </span>
            <span className="text-xs bg-slate-800/90 border border-slate-700 px-1.5 py-0.5 rounded text-amber-300 font-mono font-bold">
              Q: {queues['NORTH'] || 0}
            </span>
          </div>
          <div className="flex items-center gap-3 bg-slate-900/90 p-2 rounded-xl border border-slate-800">
            <div>
              <span className="text-[9px] block text-slate-400 text-center font-mono">Desired</span>
              <SignalIndicator state={desiredSignals['NORTH']} size="sm" />
            </div>
            <div className="border-l border-slate-800 pl-2">
              <span className="text-[9px] block text-slate-400 text-center font-mono">Actual</span>
              <SignalIndicator state={actualSignals['NORTH']} size="sm" />
            </div>
          </div>
          {getMismatch('NORTH') && (
            <span className="text-[9px] text-rose-400 font-semibold mt-0.5 animate-pulse">Mismatch!</span>
          )}
        </div>

        {/* SOUTH Approach */}
        <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex flex-col items-center z-20">
          {getMismatch('SOUTH') && (
            <span className="text-[9px] text-rose-400 font-semibold mb-0.5 animate-pulse">Mismatch!</span>
          )}
          <div className="flex items-center gap-3 bg-slate-900/90 p-2 rounded-xl border border-slate-800">
            <div>
              <span className="text-[9px] block text-slate-400 text-center font-mono">Desired</span>
              <SignalIndicator state={desiredSignals['SOUTH']} size="sm" />
            </div>
            <div className="border-l border-slate-800 pl-2">
              <span className="text-[9px] block text-slate-400 text-center font-mono">Actual</span>
              <SignalIndicator state={actualSignals['SOUTH']} size="sm" />
            </div>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className={`px-2 py-0.5 rounded text-xs font-bold font-mono ${
              activeEmergency === 'SOUTH' ? 'bg-rose-600 text-white animate-bounce' : 'bg-slate-800 text-slate-200 border border-slate-700'
            }`}>
              SOUTH {activeEmergency === 'SOUTH' && '🚨'}
            </span>
            <span className="text-xs bg-slate-800/90 border border-slate-700 px-1.5 py-0.5 rounded text-amber-300 font-mono font-bold">
              Q: {queues['SOUTH'] || 0}
            </span>
          </div>
        </div>

        {/* WEST Approach */}
        <div className="absolute left-2 top-1/2 -translate-y-1/2 flex flex-col items-center z-20">
          <div className="flex items-center gap-2 mb-1">
            <span className={`px-2 py-0.5 rounded text-xs font-bold font-mono ${
              activeEmergency === 'WEST' ? 'bg-rose-600 text-white animate-bounce' : 'bg-slate-800 text-slate-200 border border-slate-700'
            }`}>
              WEST {activeEmergency === 'WEST' && '🚨'}
            </span>
            <span className="text-xs bg-slate-800/90 border border-slate-700 px-1.5 py-0.5 rounded text-amber-300 font-mono font-bold">
              Q: {queues['WEST'] || 0}
            </span>
          </div>
          <div className="flex items-center gap-3 bg-slate-900/90 p-2 rounded-xl border border-slate-800">
            <div>
              <span className="text-[9px] block text-slate-400 text-center font-mono">Desired</span>
              <SignalIndicator state={desiredSignals['WEST']} size="sm" />
            </div>
            <div className="border-l border-slate-800 pl-2">
              <span className="text-[9px] block text-slate-400 text-center font-mono">Actual</span>
              <SignalIndicator state={actualSignals['WEST']} size="sm" />
            </div>
          </div>
          {getMismatch('WEST') && (
            <span className="text-[9px] text-rose-400 font-semibold mt-0.5 animate-pulse">Mismatch!</span>
          )}
        </div>

        {/* EAST Approach */}
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex flex-col items-center z-20">
          <div className="flex items-center gap-2 mb-1">
            <span className={`px-2 py-0.5 rounded text-xs font-bold font-mono ${
              activeEmergency === 'EAST' ? 'bg-rose-600 text-white animate-bounce' : 'bg-slate-800 text-slate-200 border border-slate-700'
            }`}>
              EAST {activeEmergency === 'EAST' && '🚨'}
            </span>
            <span className="text-xs bg-slate-800/90 border border-slate-700 px-1.5 py-0.5 rounded text-amber-300 font-mono font-bold">
              Q: {queues['EAST'] || 0}
            </span>
          </div>
          <div className="flex items-center gap-3 bg-slate-900/90 p-2 rounded-xl border border-slate-800">
            <div>
              <span className="text-[9px] block text-slate-400 text-center font-mono">Desired</span>
              <SignalIndicator state={desiredSignals['EAST']} size="sm" />
            </div>
            <div className="border-l border-slate-800 pl-2">
              <span className="text-[9px] block text-slate-400 text-center font-mono">Actual</span>
              <SignalIndicator state={actualSignals['EAST']} size="sm" />
            </div>
          </div>
          {getMismatch('EAST') && (
            <span className="text-[9px] text-rose-400 font-semibold mt-0.5 animate-pulse">Mismatch!</span>
          )}
        </div>
      </div>
    </div>
  );
}

