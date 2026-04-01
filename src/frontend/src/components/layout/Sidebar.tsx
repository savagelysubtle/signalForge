import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  History,
  BookOpen,
  LineChart,
  Settings
} from 'lucide-react';
import clsx from 'clsx';
import logoIcon from '../../assets/signalforge-logo-icon.svg';

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Recommendations' },
  { path: '/history', icon: History, label: 'History' },
  { path: '/strategies', icon: BookOpen, label: 'Strategies' },
  { path: '/insights', icon: LineChart, label: 'Insights' },
  { path: '/settings', icon: Settings, label: 'Settings' },
];

export function Sidebar() {
  return (
    <div className="w-16 flex flex-col items-center py-4 bg-bg-asphalt border-r border-border-subtle h-full shrink-0">
      <div className="mb-8 relative">
        <div className="absolute -inset-3 glow-signal rounded-full opacity-60" />
        <img src={logoIcon} alt="SignalForge" className="w-9 h-9 relative" />
      </div>

      <nav className="flex flex-col gap-2 w-full px-2">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) => clsx(
              "relative p-3 rounded-lg flex items-center justify-center transition-all duration-200 group",
              isActive
                ? "bg-accent-signal-dim text-accent-signal"
                : "text-text-muted hover:text-text-primary hover:bg-bg-steel"
            )}
            title={item.label}
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span className="absolute left-0 top-2 bottom-2 w-0.5 rounded-r bg-accent-signal" />
                )}
                <item.icon className="w-5 h-5" />
                <span className="absolute left-14 bg-bg-concrete text-text-primary text-xs px-2.5 py-1.5 rounded-md opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-50 border border-border-gutter shadow-lg shadow-black/40 font-body">
                  {item.label}
                </span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
