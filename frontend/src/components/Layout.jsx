import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { LayoutDashboard, Users, Server, Settings, LogOut } from 'lucide-react';
import { api } from '../lib/api';

const links = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/users', icon: Users, label: 'Users' },
  { to: '/nodes', icon: Server, label: 'Nodes' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export default function Layout({ admin, onLogout }) {
  const navigate = useNavigate();

  const handleLogout = async () => {
    await api.logout();
    onLogout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="w-56 bg-claw-card border-r border-claw-border flex flex-col fixed h-full">
        <div className="p-5 border-b border-claw-border">
          <h1 className="text-xl font-bold">
            <span className="text-claw-accent">Claw</span>Panel
          </h1>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {links.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-claw-accent/15 text-claw-accent font-medium'
                    : 'text-claw-muted hover:text-claw-text hover:bg-claw-border/30'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t border-claw-border">
          <div className="flex items-center justify-between px-3 py-2">
            <span className="text-sm text-claw-muted">{admin}</span>
            <button onClick={handleLogout} className="text-claw-muted hover:text-claw-red transition-colors" title="Logout">
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 ml-56 p-8">
        <Outlet />
      </main>
    </div>
  );
}
