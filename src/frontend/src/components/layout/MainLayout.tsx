import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { CommandBar } from './CommandBar';

export function MainLayout() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg-primary text-text-primary font-sans">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0">
        <CommandBar />
        <main className="flex-1 overflow-auto relative">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
