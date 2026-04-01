import { NavLink, useLocation, useSearchParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { ArrowLeft, LayoutDashboard, History, BookOpen, LineChart, Settings, LogOut } from 'lucide-react';
import clsx from 'clsx';
import logoIcon from '../../assets/signalforge-logo-icon.svg';

const navItems: { path: string; icon: typeof LayoutDashboard; label: string; end?: boolean }[] = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard', end: true },
  { path: '/history', icon: History, label: 'History' },
  { path: '/strategies', icon: BookOpen, label: 'Strategies' },
  { path: '/insights', icon: LineChart, label: 'Insights' },
  { path: '/settings', icon: Settings, label: 'Settings' },
];

export function TopBar() {
  const { user, signOut } = useAuth();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const isResultsScreen = location.pathname === '/' && searchParams.has('run');

  return (
    <header className="h-14 border-b border-border-gutter bg-bg-asphalt/80 backdrop-blur-md flex items-center px-5 shrink-0 relative z-20">
      {/* Left — Logo */}
      <NavLink to="/" className="flex items-center gap-2.5 shrink-0">
        <div className="relative">
          <div className="absolute -inset-2 glow-signal rounded-full opacity-40" />
          <img src={logoIcon} alt="SignalForge" className="w-7 h-7 relative" />
        </div>
        <span className="hidden sm:inline font-display font-bold text-text-primary text-sm tracking-tight">
          SignalForge
        </span>
      </NavLink>

      {/* Center — Nav links (absolutely centered, hidden on results screen) */}
      {!isResultsScreen && (
        <nav className="absolute left-1/2 -translate-x-1/2 flex items-center gap-0.5 md:gap-1 bg-bg-concrete/60 backdrop-blur-sm border border-border-subtle rounded-lg px-1 md:px-1.5 py-1">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.end}
              className={({ isActive }) => clsx(
                "flex items-center gap-2 px-2.5 md:px-4 py-1.5 rounded-md text-sm font-body transition-colors",
                isActive
                  ? "bg-accent-signal-dim text-accent-signal"
                  : "text-text-muted hover:text-text-primary hover:bg-bg-steel"
              )}
            >
              <item.icon className="w-4 h-4" />
              <span className="hidden md:inline">{item.label}</span>
            </NavLink>
          ))}
        </nav>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Right — Back button (results only) + User */}
      <div className="flex items-center gap-3">
        {isResultsScreen && (
          <button
            onClick={() => navigate('/')}
            className="flex items-center gap-1.5 text-sm font-body text-text-secondary hover:text-accent-signal transition-colors px-3 py-1.5 rounded-md hover:bg-bg-steel"
          >
            <ArrowLeft className="w-4 h-4" />
            <span className="hidden sm:inline">Back to Search</span>
          </button>
        )}

        {user && (
          <>
            <span className="hidden sm:inline text-xs text-text-muted font-body truncate max-w-[180px]">
              {user.email}
            </span>
            <button
              onClick={signOut}
              className="p-2 rounded-md text-text-muted hover:text-accent-loss hover:bg-accent-loss-dim transition-colors"
              title="Sign out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </>
        )}
      </div>
    </header>
  );
}
