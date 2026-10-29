import Link from 'next/link';

export default function Layout({ children }) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-lg bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 font-bold">
              🚦
            </div>
            <div>
              <Link href="/" className="font-semibold text-lg tracking-tight hover:text-amber-400 transition-colors">
                Factory Traffic Control System
              </Link>
              <p className="text-xs text-slate-400">Internal Logistics & Junction Automation</p>
            </div>
          </div>
          <nav className="flex items-center space-x-4">
            <Link
              href="/"
              className="text-sm font-medium px-3 py-1.5 rounded-md hover:bg-slate-800 transition-colors text-slate-300 hover:text-white"
            >
              Dashboard
            </Link>
            <Link
              href="/junctions/A"
              className="text-sm font-medium px-3 py-1.5 rounded-md bg-amber-500/20 text-amber-300 border border-amber-500/30 hover:bg-amber-500/30 transition-colors"
            >
              Junction A Detail
            </Link>
          </nav>
        </div>
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {children}
      </main>

      <footer className="border-t border-slate-800/80 py-4 bg-slate-950 text-center text-xs text-slate-500">
        Factory Traffic Management System • Safe Deterministic Control • DRF + Next.js
      </footer>
    </div>
  );
}

