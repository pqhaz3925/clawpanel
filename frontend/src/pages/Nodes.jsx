import { useEffect, useState, useCallback } from 'react';
import { Plus, Trash2, Power, Wifi, WifiOff } from 'lucide-react';
import { api } from '../lib/api';
import toast from 'react-hot-toast';
import Modal from '../components/Modal';

function timeAgo(ts) {
  if (!ts) return 'never';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

const PROTOCOLS = [
  { port: 443, label: 'XHTTP EXIT', color: 'bg-claw-accent/15 text-claw-accent' },
  { port: 2052, label: 'XHTTP DIRECT', color: 'bg-claw-green/15 text-claw-green' },
  { port: 53, label: 'HY2 XDNS', color: 'bg-claw-amber/15 text-claw-amber' },
  { port: 9053, label: 'HY2 XICMP', color: 'bg-claw-red/15 text-claw-red' },
];

export default function Nodes() {
  const [nodes, setNodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(() => {
    api.getNodes().then((d) => { setNodes(d.nodes); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleToggle = async (id) => {
    await api.toggleNode(id);
    toast.success('Node toggled');
    load();
  };

  const handleDelete = async (id, name) => {
    if (!confirm(`Delete node "${name}"?`)) return;
    await api.deleteNode(id);
    toast.success('Node deleted');
    load();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-claw-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Nodes</h1>
        <button onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 bg-claw-accent hover:bg-claw-accent-hover text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
          <Plus size={16} /> Add Node
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {nodes.map((n) => {
          const online = n.is_active && n.last_heartbeat && (Date.now() / 1000 - n.last_heartbeat) < 120;
          return (
            <div key={n.id} className="bg-claw-card border border-claw-border rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${online ? 'bg-claw-green/15 text-claw-green' : 'bg-claw-border/30 text-claw-muted'}`}>
                    {online ? <Wifi size={18} /> : <WifiOff size={18} />}
                  </div>
                  <div>
                    <div className="font-medium">{n.flag} {n.label || n.name}</div>
                    <div className="text-xs text-claw-muted">{n.address}</div>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button onClick={() => handleToggle(n.id)} className="p-1.5 rounded-lg hover:bg-claw-border/30 text-claw-muted hover:text-claw-amber transition-colors" title="Toggle">
                    <Power size={15} />
                  </button>
                  <button onClick={() => handleDelete(n.id, n.name)} className="p-1.5 rounded-lg hover:bg-claw-border/30 text-claw-muted hover:text-claw-red transition-colors" title="Delete">
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>

              {/* Info */}
              <div className="grid grid-cols-3 gap-2 text-xs mb-3">
                <div className="bg-claw-bg rounded-lg px-2 py-1.5">
                  <span className="text-claw-muted">Status</span>
                  <div className={online ? 'text-claw-green' : 'text-claw-red'}>{online ? 'Online' : n.is_active ? 'Offline' : 'Disabled'}</div>
                </div>
                <div className="bg-claw-bg rounded-lg px-2 py-1.5">
                  <span className="text-claw-muted">Heartbeat</span>
                  <div>{timeAgo(n.last_heartbeat)}</div>
                </div>
                <div className="bg-claw-bg rounded-lg px-2 py-1.5">
                  <span className="text-claw-muted">Agent</span>
                  <div>{n.agent_version || '—'}</div>
                </div>
              </div>

              {/* Protocols */}
              <div className="flex flex-wrap gap-1.5">
                {PROTOCOLS.map((p) => (
                  <span key={p.port} className={`text-xs px-2 py-0.5 rounded-full ${p.color}`}>
                    :{p.port} {p.label}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
        {nodes.length === 0 && (
          <div className="col-span-2 text-center text-claw-muted py-12">No nodes yet</div>
        )}
      </div>

      <CreateNodeModal open={createOpen} onClose={() => setCreateOpen(false)} onCreated={load} />
    </div>
  );
}

function CreateNodeModal({ open, onClose, onCreated }) {
  const [form, setForm] = useState({ name: '', address: '', flag: '\ud83c\uddf3\ud83c\uddf1', label: '' });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.createNode(form);
      toast.success('Node added');
      setForm({ name: '', address: '', flag: '\ud83c\uddf3\ud83c\uddf1', label: '' });
      onClose();
      onCreated();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Add Node">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm text-claw-muted mb-1">Name (internal ID)</label>
          <input type="text" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="e.g. NL1"
            className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-claw-accent" />
        </div>
        <div>
          <label className="block text-sm text-claw-muted mb-1">Address (domain/IP)</label>
          <input type="text" required value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })}
            placeholder="e.g. nl.clawvpn.lol"
            className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-claw-accent" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm text-claw-muted mb-1">Flag</label>
            <input type="text" value={form.flag} onChange={(e) => setForm({ ...form, flag: e.target.value })}
              className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-claw-accent" />
          </div>
          <div>
            <label className="block text-sm text-claw-muted mb-1">Display Label</label>
            <input type="text" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })}
              placeholder="e.g. Netherlands 1"
              className="w-full bg-claw-bg border border-claw-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-claw-accent" />
          </div>
        </div>
        <button type="submit" disabled={saving}
          className="w-full bg-claw-accent hover:bg-claw-accent-hover text-white py-2.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-50">
          {saving ? 'Adding...' : 'Add Node'}
        </button>
      </form>
    </Modal>
  );
}
