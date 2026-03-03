import { useEffect, useState } from 'react';
import { Users, Server, Activity, Shield } from 'lucide-react';
import { api } from '../lib/api';

function StatCard({ icon: Icon, label, value, sub, color }) {
  return (
    <div className="bg-claw-card border border-claw-border rounded-xl p-5">
      <div className="flex items-center gap-3 mb-3">
        <div className={`p-2 rounded-lg ${color}`}>
          <Icon size={20} />
        </div>
        <span className="text-sm text-claw-muted">{label}</span>
      </div>
      <div className="text-2xl font-bold">{value}</div>
      {sub && <div className="text-xs text-claw-muted mt-1">{sub}</div>}
    </div>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.stats().then(setStats).catch(console.error);
  }, []);

  if (!stats) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-claw-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={Users} label="Users" value={stats.total_users} sub={`${stats.active_users} active`} color="bg-claw-accent/15 text-claw-accent" />
        <StatCard icon={Server} label="Nodes" value={stats.total_nodes} sub={`${stats.online_nodes} online`} color="bg-claw-green/15 text-claw-green" />
        <StatCard icon={Activity} label="Traffic" value={stats.total_traffic} color="bg-claw-amber/15 text-claw-amber" />
        <StatCard icon={Shield} label="Protocols" value="4" sub="XHTTP \u00b7 HY2 \u00b7 XDNS \u00b7 XICMP" color="bg-claw-red/15 text-claw-red" />
      </div>
    </div>
  );
}
