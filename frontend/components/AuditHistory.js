export default function AuditHistory({ history = [], loading = false }) {
  if (loading && history.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 text-center text-xs text-slate-500">
        Loading event audit log...
      </div>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
      <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-3">
        <div>
          <h3 className="font-semibold text-slate-200 text-sm tracking-wide uppercase flex items-center gap-2">
            <span>📜 System Audit History Log</span>
          </h3>
          <p className="text-xs text-slate-400">Append-only sequence of scheduling, overrides, transitions, and hardware telemetry.</p>
        </div>
        <span className="text-xs text-slate-500 font-mono">Count: {history.length}</span>
      </div>

      <div className="overflow-x-auto max-h-80 overflow-y-auto">
        <table className="w-full text-left text-xs text-slate-300">
          <thead className="bg-slate-950/70 text-[11px] text-slate-400 uppercase font-mono sticky top-0 border-b border-slate-800">
            <tr>
              <th className="py-2 px-2.5">Time</th>
              <th className="py-2 px-2.5">Event Type</th>
              <th className="py-2 px-2.5">Direction</th>
              <th className="py-2 px-2.5">Transition / State</th>
              <th className="py-2 px-2.5">Ref ID</th>
              <th className="py-2 px-2.5">Reason / Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
            {history.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center py-6 text-slate-500 font-sans">
                  No recorded events yet for this junction.
                </td>
              </tr>
            ) : (
              history.map((item, idx) => (
                <tr key={item.id || idx} className="hover:bg-slate-800/40 transition-colors">
                  <td className="py-2 px-2.5 text-slate-400 whitespace-nowrap">
                    {item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : '-'}
                  </td>
                  <td className="py-2 px-2.5 font-bold whitespace-nowrap">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                      item.event_type.includes('EMERGENCY') ? 'bg-rose-950 text-rose-300 border border-rose-800' :
                      item.event_type.includes('MANUAL') ? 'bg-amber-950 text-amber-300 border border-amber-800' :
                      item.event_type.includes('DUPLICATE') ? 'bg-purple-950 text-purple-300 border border-purple-800' :
                      item.event_type.includes('CONTROLLER') ? 'bg-blue-950 text-blue-300 border border-blue-800' :
                      'bg-slate-800 text-slate-300'
                    }`}>
                      {item.event_type}
                    </span>
                  </td>
                  <td className="py-2 px-2.5 text-slate-300 whitespace-nowrap">
                    {item.direction || '—'}
                  </td>
                  <td className="py-2 px-2.5 text-slate-400 whitespace-nowrap">
                    {item.previous_state && item.new_state ? (
                      <span>{item.previous_state} → <strong className="text-slate-200">{item.new_state}</strong></span>
                    ) : (
                      item.new_state || '—'
                    )}
                  </td>
                  <td className="py-2 px-2.5 text-slate-400 whitespace-nowrap text-[10px]">
                    {item.event_id || item.command_id || '—'}
                  </td>
                  <td className="py-2 px-2.5 text-slate-300 max-w-xs truncate" title={item.reason || JSON.stringify(item.details)}>
                    {item.reason || (item.details ? JSON.stringify(item.details) : '—')}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

