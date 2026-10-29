export default function SignalIndicator({ state = 'RED', size = 'md', label = null }) {
  const normalized = (state || 'UNKNOWN').toUpperCase();

  const isRed = normalized === 'RED';
  const isYellow = normalized === 'YELLOW';
  const isGreen = normalized === 'GREEN';
  const isUnknown = normalized === 'UNKNOWN';

  const dotSize = size === 'sm' ? 'w-3 h-3' : size === 'lg' ? 'w-6 h-6' : 'w-4 h-4';
  const boxPadding = size === 'sm' ? 'p-1' : size === 'lg' ? 'p-2' : 'p-1.5';

  return (
    <div className="flex flex-col items-center">
      {label && <span className="text-[10px] uppercase font-bold text-slate-400 mb-1">{label}</span>}
      <div className={`bg-slate-900 border border-slate-700/80 rounded-full flex flex-col space-y-1.5 ${boxPadding} shadow-inner`}>
        {/* Red light */}
        <div
          className={`${dotSize} rounded-full transition-all duration-300 ${
            isRed
              ? 'bg-rose-500 shadow-[0_0_12px_rgba(244,63,94,0.9)] animate-pulse'
              : 'bg-rose-950/40 border border-rose-900/30'
          }`}
        />
        {/* Yellow light */}
        <div
          className={`${dotSize} rounded-full transition-all duration-300 ${
            isYellow
              ? 'bg-amber-400 shadow-[0_0_12px_rgba(251,191,36,0.9)] animate-pulse'
              : 'bg-amber-950/40 border border-amber-900/30'
          }`}
        />
        {/* Green light */}
        <div
          className={`${dotSize} rounded-full transition-all duration-300 ${
            isGreen
              ? 'bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.9)] animate-pulse'
              : 'bg-emerald-950/40 border border-emerald-900/30'
          }`}
        />
      </div>
      {isUnknown && (
        <span className="text-[10px] text-orange-400 font-mono mt-1 font-semibold">UNCERTAIN</span>
      )}
    </div>
  );
}

