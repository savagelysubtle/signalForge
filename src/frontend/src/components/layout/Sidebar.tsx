import { NavLink } from 'react-router-dom';
import { 
  LayoutDashboard, 
  History, 
  BookOpen, 
  LineChart, 
  Settings 
} from 'lucide-react';
import clsx from 'clsx';

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Recommendations' },
  { path: '/history', icon: History, label: 'History' },
  { path: '/strategies', icon: BookOpen, label: 'Strategies' },
  { path: '/insights', icon: LineChart, label: 'Insights' },
  { path: '/settings', icon: Settings, label: 'Settings' },
];

export function Sidebar() {
  return (
    <div className="w-16 flex flex-col items-center py-4 bg-bg-secondary border-r border-border h-full shrink-0">
      <div className="mb-8">
        <div className="w-8 h-8 bg-accent-blue rounded-md flex items-center justify-center text-bg-primary font-bold">
          SF
        </div>
      </div>
      
      <nav className="flex flex-col gap-4 w-full px-2">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) => clsx(
              "p-3 rounded-lg flex items-center justify-center transition-colors group relative",
              isActive 
                ? "bg-bg-tertiary text-accent-blue" 
                : "text-text-secondary hover:text-text-primary hover:bg-bg-tertiary"
            )}
            title={item.label}
          >
            <item.icon className="w-5 h-5" />
            <span className="absolute left-14 bg-bg-tertiary text-text-primary text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-50 border border-border">
              {item.label}
            </span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
