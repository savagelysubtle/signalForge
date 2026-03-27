import { Outlet } from 'react-router-dom';
import { TopBar } from './TopBar';

export function MainLayout() {
  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-bg-void text-text-primary font-body">
      <TopBar />
      <main className="flex-1 overflow-auto relative">
        {/* Background layers */}
        <div className="fixed inset-0 bg-urban-finance pointer-events-none z-0" />
        <div className="fixed inset-0 bg-grid-fade pointer-events-none z-0" />
        <div className="fixed inset-0 bg-noise pointer-events-none z-0" />
        <div className="relative z-10 h-full">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
