export default function AlertBanner({ activeEmergency, controllerStatus, desiredSignals = {}, actualSignals = {}, transitionState }) {
  const alerts = [];

  if (activeEmergency) {
    alerts.push({
      type: 'danger',
      title: 'Active Emergency Preemption',
      message: `Emergency vehicle detected approaching from direction: ${activeEmergency}. Priority safe clearance sequence initiated.`,
    });
  }

  if (controllerStatus === 'OFFLINE' || controllerStatus === 'DEGRADED') {
    alerts.push({
      type: 'warning',
      title: `Controller Hardware Status: ${controllerStatus}`,
      message: 'Field hardware communication degraded. Normal phase switching paused until controller link is verified.',
    });
  }

  // Check for desired vs actual signal mismatch
  const mismatchedDirs = Object.keys(desiredSignals).filter(
    (dir) => actualSignals[dir] && desiredSignals[dir] !== actualSignals[dir]
  );

  if (mismatchedDirs.length > 0) {
    alerts.push({
      type: 'info',
      title: 'Signal State Awaiting Physical Confirmation',
      message: `Pending confirmation on directions: ${mismatchedDirs.join(', ')}. Waiting for controller ACK.`,
    });
  }

  if (alerts.length === 0) return null;

  return (
    <div className="space-y-2 mb-6">
      {alerts.map((alert, idx) => (
        <div
          key={idx}
          className={`px-4 py-3 rounded-xl border flex items-start space-x-3 text-xs ${
            alert.type === 'danger'
              ? 'bg-rose-950/70 border-rose-800 text-rose-200'
              : alert.type === 'warning'
              ? 'bg-amber-950/70 border-amber-800 text-amber-200'
              : 'bg-blue-950/70 border-blue-800 text-blue-200'
          }`}
        >
          <span className="text-base select-none">
            {alert.type === 'danger' ? '🚨' : alert.type === 'warning' ? '⚠️' : '⏳'}
          </span>
          <div className="flex-1">
            <h4 className="font-bold uppercase tracking-wider text-[11px]">{alert.title}</h4>
            <p className="mt-0.5 opacity-90">{alert.message}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

